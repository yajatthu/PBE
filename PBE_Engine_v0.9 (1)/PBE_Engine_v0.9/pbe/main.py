import json, logging, time
from datetime import datetime, timezone
from collections import defaultdict, deque
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator
from pbe.core.engine import PBEEngine
from pbe.core.schemas import DemoEventRequest
from pbe.db import db, init_db
from pbe.security import hash_password, verify_password, issue_token, decode_token, require_role, validate_runtime_config
from pbe.integrations.composio import ComposioClient
from pbe.integrations.tool_contracts import normalize_tool, normalize_account_items, validate_tool_arguments, safe_slug
from pbe.uol import normalize_composio_event, persist_and_queue
from pbe.settings import settings

log=logging.getLogger(__name__)
app=FastAPI(title="Polymorphic Business Engine",version="0.9.0")
_allowed_origins=[x.strip() for x in settings.PBE_ALLOWED_ORIGINS.split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins, allow_credentials=False, allow_methods=["GET","POST","OPTIONS"], allow_headers=["Authorization","Content-Type","webhook-id","webhook-timestamp","webhook-signature"])
app.mount("/static",StaticFiles(directory="pbe/static"),name="static")
_engines={}
_rate_buckets=defaultdict(deque)

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)
    tenant_name: str = Field(default="PBE Demo Company", min_length=1, max_length=120)
    workspace_name: str = Field(default="Operations", min_length=1, max_length=120)
    @field_validator("password")
    @classmethod
    def password_policy(cls,v):
        from pbe.security import validate_password
        validate_password(v); return v
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
class ConnectRequest(BaseModel):
    auth_config_id: str|None = Field(default=None, min_length=1, max_length=200)
    toolkit_slug: str|None = Field(default=None, min_length=1, max_length=100)
    callback_url: str|None = Field(default=None, max_length=2048)
    @field_validator("auth_config_id", "toolkit_slug")
    @classmethod
    def clean_connect_fields(cls,v): return v.strip() if v else v
class PlanRequest(BaseModel):
    objective: str = Field(min_length=8, max_length=4000)
    services: list[str] = Field(default_factory=list, max_length=8)
    @field_validator("services")
    @classmethod
    def clean_services(cls,v): return list(dict.fromkeys(x.strip().lower() for x in v if x and x.strip()))
class ExecutePlanActionRequest(BaseModel):
    connected_account_id: str = Field(min_length=1, max_length=200)
    confirm: bool = False

class TriggerRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=200)
    connected_account_id: str|None = Field(default=None, max_length=200)
    trigger_config: dict = Field(default_factory=dict)

def _rate_limit(request: Request, limit: int):
    now=time.monotonic(); key=(request.client.host if request.client else "unknown", request.url.path)
    q=_rate_buckets[key]
    while q and now-q[0] > 60: q.popleft()
    if len(q) >= limit: raise HTTPException(429,"Rate limit exceeded; wait before retrying")
    q.append(now)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path=request.url.path
    if path.startswith("/api/"):
        auth_path=path in {"/api/auth/register","/api/auth/login"}
        try: _rate_limit(request, settings.PBE_AUTH_RATE_LIMIT_PER_MINUTE if auth_path else settings.PBE_RATE_LIMIT_PER_MINUTE)
        except HTTPException as exc: return JSONResponse(status_code=exc.status_code, content={"detail":exc.detail})
    return await call_next(request)

def auth(request: Request):
    value=request.headers.get("Authorization","")
    if not value.startswith("Bearer "): raise HTTPException(401,"Bearer token required")
    try: claims=decode_token(value[7:])
    except Exception: raise HTTPException(401,"Invalid or expired token")
    # Re-check current membership so removed members/role changes take effect immediately.
    with db() as conn:
        row=conn.execute("SELECT m.role,w.tenant_id FROM memberships m JOIN workspaces w ON w.id=m.workspace_id WHERE m.user_id=%s AND m.workspace_id=%s",(claims.get("sub"),claims.get("workspace_id"))).fetchone()
    if not row or str(row[1]) != str(claims.get("tenant_id")): raise HTTPException(401,"Workspace membership is no longer valid")
    claims["role"]=row[0]
    return claims

def workspace_engine(claims):
    key=(str(claims["tenant_id"]),str(claims["workspace_id"]))
    if key not in _engines: _engines[key]=PBEEngine(*key)
    return _engines[key]

@app.on_event("startup")
def startup():
    validate_runtime_config()
    init_db()  # fail loudly with a useful schema/database error instead of silently continuing

async def _run_openrouter_final_check(objective: str, action_summaries: list[dict]) -> dict:
    """Model-assisted final consistency check on minimal execution metadata, never raw provider payloads."""
    from pbe.services.openrouter import OpenRouterClient
    client = OpenRouterClient()
    if not client.enabled:
        return {"status": "NOT_RUN", "summary": "OpenRouter is not configured; final model review was not run.", "checks": []}
    system = """You are PBE's final workflow reviewer. Inspect only the supplied objective and action execution metadata.
Return a JSON object with keys decision (PASS or NEEDS_HUMAN_REVIEW), summary (max 500 chars), checks (array of short strings).
PASS means only that the listed actions have success records and the workflow trace is internally consistent. It does NOT mean you independently verified external application state, business correctness, or production readiness. If any action is missing/failed/ambiguous, choose NEEDS_HUMAN_REVIEW. Never claim external state was independently verified."""
    payload = {"objective": objective[:2000], "action_execution_metadata": action_summaries[:20]}
    try:
        raw = await client.chat(system, json.dumps(payload, ensure_ascii=False))
        parsed = json.loads(raw or "{}")
        decision = parsed.get("decision")
        if decision not in {"PASS", "NEEDS_HUMAN_REVIEW"}:
            return {"status": "INVALID_RESPONSE", "summary": "OpenRouter returned an unrecognized final-review decision.", "checks": []}
        return {"status": decision, "summary": str(parsed.get("summary", ""))[:500], "checks": [str(x)[:200] for x in parsed.get("checks", [])[:10]]}
    except Exception as exc:
        log.warning("OpenRouter final workflow review failed (%s)", type(exc).__name__)
        return {"status": "FAILED", "summary": "OpenRouter final review failed; human review is required.", "checks": []}


def _workflow_event(claims, plan_id: str, event_type: str, title: str, detail: str = "", progress: int | None = None, expected_minutes: int | None = None, metadata: dict | None = None):
    """Persist a tenant/workspace-scoped workflow event without storing secrets or raw provider payloads."""
    try:
        with db() as conn:
            conn.execute(
                """INSERT INTO workflow_timeline_events
                (id,tenant_id,workspace_id,plan_id,actor_id,event_type,title,detail,progress,expected_minutes,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (str(uuid4()), claims["tenant_id"], claims["workspace_id"], plan_id,
                 claims.get("sub"), event_type, title[:160], detail[:1000],
                 progress, expected_minutes, json.dumps(metadata or {}))
            )
    except Exception:
        # Timeline telemetry must not turn a successful business action into a failure.
        log.exception("Could not persist workflow timeline event for plan %s", plan_id)


@app.get("/")
def home(): return FileResponse("pbe/static/index.html")
@app.get("/health")
def health():
    try:
        with db() as conn: conn.execute("SELECT 1")
        return {"status":"ok","database":True,"version":"0.9.0","integrations":{"openrouter_configured":bool(settings.OPENROUTER_API_KEY),"composio_configured":bool(settings.COMPOSIO_API_KEY)}}
    except Exception:
        raise HTTPException(503,"Database health check failed")

@app.post("/api/auth/register")
def register(req:RegisterRequest):
    uid,tid,wid=str(uuid4()),str(uuid4()),str(uuid4())
    try:
        with db() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email=%s",(str(req.email).lower(),)).fetchone(): raise HTTPException(409,"Email already registered")
            conn.execute("INSERT INTO tenants(id,name) VALUES (%s,%s)",(tid,req.tenant_name.strip()))
            conn.execute("INSERT INTO users(id,email,password_hash) VALUES (%s,%s,%s)",(uid,str(req.email).lower(),hash_password(req.password)))
            conn.execute("INSERT INTO workspaces(id,tenant_id,name) VALUES (%s,%s,%s)",(wid,tid,req.workspace_name.strip()))
            conn.execute("INSERT INTO memberships(user_id,workspace_id,role) VALUES (%s,%s,'OWNER')",(uid,wid))
    except HTTPException: raise
    except Exception as exc:
        log.exception("Registration failed")
        raise HTTPException(500,"Registration could not be completed; check database logs") from exc
    return {"access_token":issue_token(uid,wid,tid,"OWNER"),"user_id":uid,"tenant_id":tid,"workspace_id":wid,"role":"OWNER"}

@app.post("/api/auth/login")
def login(req:LoginRequest):
    with db() as conn:
        rows=conn.execute("SELECT u.id,u.password_hash,m.workspace_id,w.tenant_id,m.role FROM users u JOIN memberships m ON m.user_id=u.id JOIN workspaces w ON w.id=m.workspace_id WHERE lower(u.email)=lower(%s) ORDER BY w.created_at ASC",(str(req.email),)).fetchall()
    if not rows or not verify_password(req.password,rows[0][1]): raise HTTPException(401,"Invalid credentials")
    row=rows[0]
    return {"access_token":issue_token(str(row[0]),str(row[2]),str(row[3]),row[4]),"user_id":str(row[0]),"tenant_id":str(row[3]),"workspace_id":str(row[2]),"role":row[4]}

@app.get("/api/me")
def me(claims=Depends(auth)): return claims

@app.post("/api/composio/connect")
async def composio_connect(req:ConnectRequest, claims=Depends(auth)):
    if not settings.COMPOSIO_API_KEY: raise HTTPException(503,"Composio is not configured on this server")
    if req.callback_url:
        from urllib.parse import urlparse
        callback=urlparse(req.callback_url); app_url=urlparse(settings.PBE_APP_URL)
        if callback.scheme not in {"https","http"} or callback.netloc != app_url.netloc:
            raise HTTPException(400,"Callback URL must use the configured PBE_APP_URL host")
    try: configured=json.loads(settings.COMPOSIO_AUTH_CONFIGS or "{}")
    except Exception: configured={}
    if req.auth_config_id:
        require_role(claims,"OWNER","ADMIN")
        allowed_config_ids={str(v) for v in configured.values() if v}
        if req.auth_config_id not in allowed_config_ids:
            raise HTTPException(400,"Auth-config IDs must be configured on the server; arbitrary IDs are not accepted")
    auth_config_id=req.auth_config_id
    if not auth_config_id and req.toolkit_slug:
        auth_config_id=configured.get(req.toolkit_slug.lower()) or configured.get(req.toolkit_slug.lower().replace("_",""))
    if not auth_config_id:
        raise HTTPException(400,"This service is not configured yet. Ask the PBE administrator to add its Composio auth-config ID once.")
    try: return await ComposioClient().create_auth_link(claims["sub"],auth_config_id,req.callback_url)
    except Exception as exc:
        log.exception("Composio auth-link request failed")
        raise HTTPException(502,"Could not create Composio authorization link") from exc

@app.get("/api/composio/accounts")
async def composio_accounts(claims=Depends(auth)):
    if not settings.COMPOSIO_API_KEY: raise HTTPException(503,"Composio is not configured on this server")
    try: return await ComposioClient().list_accounts(claims["sub"])
    except Exception as exc:
        log.exception("Composio account listing failed")
        raise HTTPException(502,"Could not retrieve connected accounts") from exc

@app.post("/api/composio/triggers")
async def composio_trigger(req:TriggerRequest, claims=Depends(auth)):
    require_role(claims,"OWNER","ADMIN")
    if not settings.COMPOSIO_API_KEY: raise HTTPException(503,"Composio is not configured on this server")
    # Never accept a user ID from the client; the authenticated identity is authoritative.
    if req.connected_account_id:
        try:
            accounts=await ComposioClient().list_accounts(claims["sub"])
            def _items(value):
                if isinstance(value,dict):
                    if value.get("id")==req.connected_account_id or value.get("connected_account_id")==req.connected_account_id:
                        owner=value.get("user_id") or value.get("userId")
                        return owner is None or str(owner)==str(claims["sub"])
                    return any(_items(v) for v in value.values() if isinstance(v,(dict,list)))
                if isinstance(value,list): return any(_items(v) for v in value)
                return False
            if not _items(accounts): raise HTTPException(403,"Connected account was not found for the authenticated user")
        except HTTPException: raise
        except Exception as exc:
            log.exception("Could not verify Composio account ownership")
            raise HTTPException(502,"Could not verify connected account ownership") from exc
    try: return await ComposioClient().create_trigger(req.slug,claims["sub"],req.connected_account_id,req.trigger_config)
    except Exception as exc:
        log.exception("Composio trigger creation failed")
        raise HTTPException(502,"Could not create Composio trigger") from exc

@app.post("/api/composio/webhook")
async def composio_webhook(request:Request):
    raw=await request.body(); headers=request.headers; client=ComposioClient()
    secret=settings.COMPOSIO_WEBHOOK_SECRET
    if not client.verify_webhook(raw,headers.get("webhook-id",""),headers.get("webhook-timestamp",""),headers.get("webhook-signature",""),secret): raise HTTPException(401,"Invalid webhook signature")
    stamp=headers.get("webhook-timestamp","")
    try:
        # Composio signatures use a Unix timestamp; reject stale/future deliveries to limit replay.
        ts=float(stamp); age=abs(datetime.now(timezone.utc).timestamp()-ts)
        if age > settings.PBE_WEBHOOK_MAX_AGE_SECONDS: raise HTTPException(401,"Webhook timestamp is outside the allowed window")
    except ValueError: raise HTTPException(401,"Invalid webhook timestamp")
    try: payload=json.loads(raw)
    except Exception: raise HTTPException(400,"Invalid webhook JSON")
    metadata=payload.get("metadata",{}) if isinstance(payload,dict) else {}
    user_id=metadata.get("user_id"); requested_workspace=metadata.get("workspace_id")
    if not user_id: raise HTTPException(422,"Webhook metadata is missing user_id")
    with db() as conn:
        if requested_workspace:
            rows=conn.execute("SELECT w.tenant_id,w.id FROM users u JOIN memberships m ON m.user_id=u.id JOIN workspaces w ON w.id=m.workspace_id WHERE u.id=%s AND w.id=%s",(user_id,requested_workspace)).fetchall()
        else:
            rows=conn.execute("SELECT w.tenant_id,w.id FROM users u JOIN memberships m ON m.user_id=u.id JOIN workspaces w ON w.id=m.workspace_id WHERE u.id=%s",(user_id,)).fetchall()
    if len(rows)!=1: raise HTTPException(422,"Webhook user must resolve to exactly one workspace; include a valid workspace_id in metadata")
    event=normalize_composio_event(payload)
    try: inserted=persist_and_queue(event,str(rows[0][0]),str(rows[0][1]))
    except Exception as exc:
        log.exception("Could not persist/queue Composio webhook")
        raise HTTPException(503,"Webhook was verified but could not be queued") from exc
    return {"status":"accepted" if inserted else "duplicate_ignored","event_id":event["event_id"]}

@app.get("/api/composio/catalog")
def composio_catalog(claims=Depends(auth)):
    """A friendly service picker; auth-config IDs remain server-side."""
    try: configured=json.loads(settings.COMPOSIO_AUTH_CONFIGS or "{}")
    except Exception: configured={}
    known=[("canva","Canva","Designs and social graphics"),("figma","Figma","Interface and prototype design"),("notion","Notion","Documents and workspace knowledge"),("google_docs","Google Docs","Documents and writing"),("google_sheets","Google Sheets","Spreadsheets and tracking"),("slack","Slack","Team messages"),("gmail","Gmail","Email workflows")]
    services=[]
    for slug,name,description in known:
        auth_id=configured.get(slug) or configured.get(slug.replace("_",""))
        services.append({"slug":slug,"name":name,"description":description,"configured":bool(auth_id)})
    return {"services":services,"message":"PBE uses the permissions granted in the provider's authorization screen. Only configured services can be connected."}

@app.get("/api/composio/tools")
async def composio_tools(toolkit_slug:str|None=None, search:str|None=None, claims=Depends(auth)):
    if not settings.COMPOSIO_API_KEY: raise HTTPException(503,"Composio is not configured on this server")
    if toolkit_slug and not safe_slug(toolkit_slug): raise HTTPException(400,"Invalid toolkit slug")
    try:
        items=await ComposioClient().list_tools(toolkit_slug,search,60)
        safe=[]
        for item in items:
            if not isinstance(item,dict): continue
            normalized=normalize_tool(item,toolkit_slug or "unknown")
            if normalized: safe.append(normalized)
        return {"tools":safe,"count":len(safe)}
    except Exception as exc:
        log.exception("Composio tool discovery failed")
        raise HTTPException(502,"Could not load available actions from Composio") from exc

@app.post("/api/pbe/plan")
async def create_saas_plan(req:PlanRequest, claims=Depends(auth)):
    require_role(claims,"OWNER","ADMIN","MEMBER")
    from pbe.services.saas_planner import make_plan
    from pbe.services.saas_plans_store import create_plan
    allowed_services={"canva","figma","notion","google_docs","google_sheets","slack","gmail"}
    services=list(dict.fromkeys(req.services))
    unknown=set(services)-allowed_services
    if unknown: raise HTTPException(400,"Unsupported service selection: "+", ".join(sorted(unknown)))
    available=[]; limitations=[]
    if settings.COMPOSIO_API_KEY and services:
        client=ComposioClient()
        for service in services[:4]:
            try:
                rows=await client.list_tools(service,limit=30)
                for item in rows:
                    if isinstance(item,dict):
                        normalized=normalize_tool(item,service)
                        if normalized and normalized["toolkit"].lower() in {service,service.replace("_",""),service.replace("_","-")}:
                            available.append(normalized)
            except Exception:
                log.exception("Tool discovery failed for selected toolkit %s",service)
                limitations.append(f"Could not discover actions for {service}; PBE will not propose an executable action for it.")
    # Avoid a planner inventing tools: only exact discovered slugs and selected toolkits are sent.
    unique={x["slug"]:x for x in available}
    available=list(unique.values())
    current=workspace_engine(claims).state().get("modules",[])
    try: plan=await make_plan(req.objective,services,available,current)
    except Exception as exc:
        log.exception("Capability planning failed")
        raise HTTPException(502,"PBE could not create a valid plan. Check OpenRouter configuration and try again.") from exc
    discovered={x["slug"]:x for x in available}
    filtered=[]
    for action in plan.get("tool_actions",[]):
        tool=discovered.get(action.get("tool_slug"))
        if not tool: continue
        if tool["toolkit"] not in services and tool["toolkit"].replace("-","_") not in services: continue
        action["toolkit"]=tool["toolkit"]
        filtered.append(action)
    plan["tool_actions"]=filtered
    if not settings.OPENROUTER_API_KEY:
        limitations.append("OpenRouter is not configured; this is a rule-based demo plan, not model-generated analysis.")
    if not settings.COMPOSIO_API_KEY:
        limitations.append("Composio is not configured; no live connected-tool actions can run.")
    if not available and services:
        limitations.append("No tools were discovered for the selected services. PBE will not invent executable actions.")
    if limitations: plan["limitations"]=(plan.get("limitations") or [])+limitations
    saved=create_plan(claims["tenant_id"],claims["workspace_id"],claims["sub"],req.objective,services,plan)
    _workflow_event(claims, saved["id"], "PLAN_CREATED", "Objective received", "PBE captured the requested outcome and prepared a capability plan.", 5, plan.get("estimated_duration_minutes", 15), {"service_count": len(services)})
    _workflow_event(claims, saved["id"], "PLAN_READY", "Capability plan ready", "Review the plan, tool actions, estimated duration, and permissions before approval.", 15, plan.get("estimated_duration_minutes", 15), {"tool_action_count": len(plan.get("tool_actions", [])), "native_capability_count": len(plan.get("native_capabilities", []))})
    try:
        from pbe.services.audit import record
        record(claims["tenant_id"],claims["workspace_id"],claims["sub"],"SAAS_CAPABILITY_PLAN_CREATED",{"plan_id":saved["id"],"services":services,"tool_action_count":len(plan.get("tool_actions",[])),"native_capability_count":len(plan.get("native_capabilities",[]))})
    except Exception: log.exception("Could not record plan audit event")
    return saved

@app.post("/api/pbe/plans/{plan_id}/capabilities/{capability_index}/submit-to-engine")
async def submit_native_capability_to_engine(plan_id:str,capability_index:int,claims=Depends(auth)):
    """Feed a selected capability into PBE's existing Observation-to-Code pipeline."""
    require_role(claims,"OWNER","ADMIN")
    from pbe.services.saas_plans_store import get_plan, update_plan_document
    plan=get_plan(claims["tenant_id"],claims["workspace_id"],plan_id)
    if not plan: raise HTTPException(404,"Plan not found in this workspace")
    if plan["status"]!="APPROVED": raise HTTPException(409,"Approve the capability plan before submitting work to the PBE engine")
    capabilities=plan["plan"].get("native_capabilities",[])
    if capability_index<0 or capability_index>=len(capabilities): raise HTTPException(404,"Native capability not found")
    capability=capabilities[capability_index]
    if capability.get("source_event_id") or capability.get("engine_submission_status") in {"SUBMITTED", "OBSERVED_NO_MODULE"}:
        raise HTTPException(409,"This capability was already submitted to the PBE engine. Review the existing module registry before submitting again.")
    steps=capability.get("implementation_steps",[])
    message=(f"Build a PBE-native capability from this user-approved request.\n"
             f"Business objective: {plan['objective']}\n"
             f"Capability name: {capability.get('name','Native capability')}\n"
             f"Capability to replace: {capability.get('replaces','unspecified')}\n"
             f"Required capability: {capability.get('capability','')}\n"
             f"Implementation steps: {'; '.join(str(x) for x in steps)}\n"
             "Create a narrow, tenant-scoped module. Do not copy proprietary source code or claim it is deployed until separately tested and deployed.")[:3900]
    req=DemoEventRequest(tenant_id=claims["tenant_id"],event_type="native_capability_request",customer="PBE workspace owner",message=message)
    engine=workspace_engine(claims)
    event=engine.ingest(req)
    try:
        with db() as conn:
            conn.execute("INSERT INTO uol_events(event_id,tenant_id,workspace_id,timestamp,source_vector,entity_context,payload_hash,anonymized_telemetry,processing_status,processed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PROCESSED',now()) ON CONFLICT (event_id) DO NOTHING",(event.event_id,claims["tenant_id"],claims["workspace_id"],event.timestamp,event.source_vector.value,json.dumps(event.entity_context),event.payload_hash,event.anonymized_telemetry))
        module=await engine.evolve(claims["tenant_id"],claims["workspace_id"])
    except Exception as exc:
        log.exception("PBE native capability submission failed")
        raise HTTPException(502,"PBE received the request but could not complete the Observation-to-Code cycle. Check the engine logs.") from exc
    capability["engine_submission_status"]="SUBMITTED"
    capability["source_event_id"]=event.event_id
    if module:
        capability["generated_module_id"]=module.module_id
        capability["engine_validation"]={"passed":module.validation.get("passed",0),"total":module.validation.get("total",0),"state":module.state.value,"deployment_status":module.deployment_status}
        capability["readiness"]="GENERATED_AND_VALIDATED" if module.state.value=="STAGED" else "VALIDATION_BLOCKED"
    else:
        capability["engine_submission_status"]="OBSERVED_NO_MODULE"
        capability["readiness"]="IN_REVIEW"
    if not update_plan_document(claims["tenant_id"],claims["workspace_id"],plan_id,plan["plan"]):
        raise HTTPException(500,"Engine ran, but the capability plan could not be updated")
    _workflow_event(claims, plan_id, "NATIVE_CAPABILITY_SUBMITTED", "Native capability submitted to engine", "The request entered the existing Observation-to-Code pipeline. Any staged module still requires review and is not a live deployment.", 65, plan["plan"].get("estimated_duration_minutes", 30), {"event_id": event.event_id, "module_id": module.module_id if module else None, "module_state": module.state.value if module else "NO_MODULE"})
    try:
        from pbe.services.audit import record
        record(claims["tenant_id"],claims["workspace_id"],claims["sub"],"NATIVE_CAPABILITY_SUBMITTED_TO_ENGINE",{"plan_id":plan_id,"capability_index":capability_index,"event_id":event.event_id,"module_id":module.module_id if module else None})
    except Exception: log.exception("Could not audit native capability submission")
    return {"status":capability["engine_submission_status"],"plan_id":plan_id,"capability_index":capability_index,"event_id":event.event_id,"module":module.model_dump(mode="json") if module else None,"message":"PBE's existing Observation-to-Code pipeline has processed this request. A staged module is not live-deployed; owner approval only updates the registry in this prototype."}


@app.get("/api/pbe/history")
def pbe_workflow_history(claims=Depends(auth)):
    """Return recent workflow plans in the authenticated workspace only."""
    from pbe.services.saas_plans_store import list_plans
    plans = list_plans(claims["tenant_id"], claims["workspace_id"], limit=50)
    return {"items": [
        {"id": p["id"], "objective": p["objective"], "status": p["status"],
         "created_at": p.get("created_at"), "estimated_duration_minutes": (p.get("plan") or {}).get("estimated_duration_minutes", 15),
         "tool_action_count": len((p.get("plan") or {}).get("tool_actions", [])),
         "native_capability_count": len((p.get("plan") or {}).get("native_capabilities", []))}
        for p in plans
    ]}

@app.get("/api/pbe/plans/{plan_id}/timeline")
def pbe_workflow_timeline(plan_id: str, claims=Depends(auth)):
    """Return persisted, workspace-scoped process history and calculated progress."""
    from pbe.services.saas_plans_store import get_plan, list_executions
    plan = get_plan(claims["tenant_id"], claims["workspace_id"], plan_id)
    if not plan:
        raise HTTPException(404, "Workflow not found in this workspace")
    with db() as conn:
        rows = conn.execute(
            """SELECT event_type,title,detail,progress,expected_minutes,metadata,created_at
            FROM workflow_timeline_events
            WHERE tenant_id=%s AND workspace_id=%s AND plan_id=%s
            ORDER BY created_at ASC LIMIT 500""",
            (claims["tenant_id"], claims["workspace_id"], plan_id)
        ).fetchall()
    timeline = [{"event_type": r[0], "title": r[1], "detail": r[2], "progress": r[3],
                 "expected_minutes": r[4], "metadata": r[5] or {}, "timestamp": r[6].isoformat()}
                for r in rows]
    executions = list_executions(claims["tenant_id"], claims["workspace_id"], plan_id)
    estimated = int((plan.get("plan") or {}).get("estimated_duration_minutes", 15) or 15)
    terminal = plan["status"] == "COMPLETED"
    latest = timeline[-1]["timestamp"] if timeline else plan.get("created_at")
    try:
        created_dt = datetime.fromisoformat(str(plan.get("created_at")).replace("Z", "+00:00"))
        expected_dt = created_dt + __import__("datetime").timedelta(minutes=estimated)
        expected_completion_at = expected_dt.isoformat()
    except Exception:
        expected_completion_at = None
    return {"plan_id": plan_id, "status": plan["status"], "objective": plan["objective"],
            "estimated_duration_minutes": estimated, "expected_completion_minutes_from_start": estimated,
            "expected_completion_at": expected_completion_at,
            "created_at": plan.get("created_at"), "latest_activity_at": latest,
            "progress": max([int(x["progress"] or 0) for x in timeline], default=0),
            "timeline": timeline, "executions": executions, "completion_is_verified": terminal}

@app.get("/api/pbe/plans")
def list_saas_plans(claims=Depends(auth)):
    from pbe.services.saas_plans_store import list_plans
    return {"plans":list_plans(claims["tenant_id"],claims["workspace_id"])}

@app.post("/api/pbe/plans/{plan_id}/approve")
def approve_saas_plan(plan_id:str, claims=Depends(auth)):
    require_role(claims,"OWNER","ADMIN")
    from pbe.services.saas_plans_store import get_plan,set_plan_status
    plan=get_plan(claims["tenant_id"],claims["workspace_id"],plan_id)
    if not plan: raise HTTPException(404,"Plan not found in this workspace")
    if plan["status"] != "PLANNED": raise HTTPException(409,f"Plan cannot be approved from its current state: {plan['status']}")
    if not set_plan_status(claims["tenant_id"],claims["workspace_id"],plan_id,"APPROVED"): raise HTTPException(409,"Could not approve plan")
    _workflow_event(claims, plan_id, "PLAN_APPROVED", "Plan approved by workspace owner", "Execution remains gated: each external action requires a separate explicit confirmation.", 25, (plan.get("plan") or {}).get("estimated_duration_minutes", 15), {"action_count": len((plan.get("plan") or {}).get("tool_actions", []))})
    return {"status":"APPROVED","plan_id":plan_id,"message":"Plan approved. Each connected-tool action still needs separate confirmation."}

@app.post("/api/pbe/plans/{plan_id}/actions/{action_index}/execute")
async def execute_saas_plan_action(plan_id:str,action_index:int,req:ExecutePlanActionRequest,claims=Depends(auth)):
    require_role(claims,"OWNER","ADMIN")
    from pbe.services.saas_plans_store import get_plan,save_execution,get_action_execution
    plan=get_plan(claims["tenant_id"],claims["workspace_id"],plan_id)
    if not plan: raise HTTPException(404,"Plan not found in this workspace")
    if plan["status"]!="APPROVED": raise HTTPException(409,"Approve the plan before running an action")
    actions=plan["plan"].get("tool_actions",[])
    if action_index<0 or action_index>=len(actions): raise HTTPException(404,"Tool action not found")
    action=actions[action_index]
    if not req.confirm: raise HTTPException(400,"Explicit confirmation is required before a connected tool can run")
    previous=get_action_execution(claims["tenant_id"],claims["workspace_id"],plan_id,action_index)
    if previous and previous["status"] in {"SUCCEEDED","RECORDED"}:
        raise HTTPException(409,"This action already has a recorded execution. Create a new plan or verify the provider state before repeating it.")
    if not settings.COMPOSIO_API_KEY: raise HTTPException(503,"Composio is not configured on this server")
    slug=safe_slug(action.get("tool_slug"))
    if not slug: raise HTTPException(400,"The plan contains an invalid tool identifier")
    client=ComposioClient()
    workflow_status = plan["status"]
    final_review_result = None
    _workflow_event(claims, plan_id, "ACTION_STARTED", "Connected-tool action started", f"Starting approved action {action_index + 1}: {action.get('title', slug)}. Provider result is pending.", 35, (plan.get("plan") or {}).get("estimated_duration_minutes", 15), {"action_index": action_index, "tool_slug": slug, "connected_account_id": req.connected_account_id})
    try:
        accounts=normalize_account_items(await client.list_accounts(claims["sub"]))
        account=next((a for a in accounts if a["id"]==req.connected_account_id),None)
        if not account: raise HTTPException(403,"Choose a connected account returned for your authenticated Composio user")
        if account["owner"] and account["owner"]!=str(claims["sub"]): raise HTTPException(403,"Connected account does not belong to the authenticated user")
        if account["status"] in {"PENDING", "EXPIRED", "FAILED", "DISCONNECTED", "REVOKED", "INACTIVE"}:
            raise HTTPException(409,"This connected account is not active. Reconnect it through Composio first.")
        expected=str(action.get("toolkit") or "").lower().replace("-","_")
        actual=account["toolkit"].lower().replace("-","_")
        if not actual or not expected:
            raise HTTPException(403,"Composio did not provide enough account metadata to verify the selected service. Refresh the connection and try again.")
        if actual not in {expected,expected.replace("_","")} and expected not in {actual,actual.replace("_","")}:
            raise HTTPException(403,"The selected connected account does not match this tool's service")
        tool_meta=await client.get_tool(slug)
        if isinstance(tool_meta,dict) and isinstance(tool_meta.get("data"),dict): tool_meta=tool_meta["data"]
        if not isinstance(tool_meta,dict): raise HTTPException(502,"Composio returned an invalid tool definition")
        fresh=normalize_tool(tool_meta,action.get("toolkit") or "unknown")
        if not fresh or fresh["slug"]!=slug: raise HTTPException(409,"The tool definition changed. Regenerate the plan before running it.")
        validate_tool_arguments(action.get("arguments",{}),fresh.get("input_schema",{}))
        result=await client.execute_tool(slug,action.get("arguments",{}),claims["sub"],req.connected_account_id)
        # Save only after the provider responds. Preserve the provider result for debugging and audit.
        saved_result={"tool_slug":slug,"toolkit":fresh["toolkit"],"result":result}
        save_execution(claims["tenant_id"],claims["workspace_id"],plan_id,action_index,saved_result,"SUCCEEDED")
        _workflow_event(claims, plan_id, "ACTION_SUCCEEDED", "Connected-tool action completed", f"Composio reported success for {action.get('title', slug)}. Review the provider result and verify the resulting state.", 55, (plan.get("plan") or {}).get("estimated_duration_minutes", 15), {"action_index": action_index, "tool_slug": slug, "connected_account_id": req.connected_account_id})
        try:
            from pbe.services.saas_plans_store import list_executions, set_plan_status
            finished = list_executions(claims["tenant_id"], claims["workspace_id"], plan_id)
            succeeded_indices = sorted({x["action_index"] for x in finished if x["status"] == "SUCCEEDED"})
            total_actions = len(actions)
            all_actions_succeeded = total_actions > 0 and len(succeeded_indices) == total_actions
            progress = min(90, 55 + int(35 * len(succeeded_indices) / max(total_actions, 1)))
            if all_actions_succeeded:
                summaries = [{"action_index": x["action_index"], "status": x["status"],
                              "action_title": actions[x["action_index"]].get("title", "Action") if x["action_index"] < len(actions) else "Action",
                              "tool_slug": (x.get("result") or {}).get("tool_slug", "unknown")}
                             for x in finished if x["action_index"] in succeeded_indices]
                review = await _run_openrouter_final_check(plan["objective"], summaries)
                final_review_result = review
                _workflow_event(claims, plan_id, "FINAL_CHECKS", "OpenRouter final workflow review",
                    review["summary"] or "Final review returned no summary.", 95 if review["status"] == "PASS" else 85,
                    (plan.get("plan") or {}).get("estimated_duration_minutes", 15),
                    {"review_status": review["status"], "checks": review.get("checks", []),
                     "external_state_independently_verified": False})
                if review["status"] == "PASS":
                    set_plan_status(claims["tenant_id"], claims["workspace_id"], plan_id, "COMPLETED")
                    workflow_status = "COMPLETED"
                    _workflow_event(claims, plan_id, "WORKFLOW_ACTIONS_COMPLETE", "Workflow actions completed", "All planned connected-tool actions have success records and OpenRouter reviewed the execution trace. Human verification of resulting application state is still required.", 100, 0, {"review_status": "PASS", "external_state_independently_verified": False})
            else:
                _workflow_event(claims, plan_id, "ACTION_PROGRESS", "Workflow progressing", f"{len(succeeded_indices)} of {total_actions} connected-tool actions have success records.", progress, (plan.get("plan") or {}).get("estimated_duration_minutes", 15), {"succeeded_actions": len(succeeded_indices), "total_actions": total_actions})
            record(claims["tenant_id"],claims["workspace_id"],claims["sub"],"COMPOSIO_TOOL_EXECUTED",{"plan_id":plan_id,"action_index":action_index,"tool_slug":slug,"connected_account_id":req.connected_account_id})
        except Exception: log.exception("Could not write connected-tool audit record")
        return {"status":"EXECUTED","workflow_status":workflow_status,"final_review":final_review_result,"action_index":action_index,"tool_slug":slug,"result":result,"repeat_protection":"This action index is now recorded and will not be executed twice from the same plan."}
    except HTTPException as exc:
        _workflow_event(claims, plan_id, "ACTION_BLOCKED", "Connected-tool action blocked", "PBE stopped the action because an account, permission, approval, or tool-contract check did not pass.", 35, (plan.get("plan") or {}).get("estimated_duration_minutes", 15), {"action_index": action_index, "tool_slug": slug, "http_status": exc.status_code})
        raise
    except ValueError as exc:
        _workflow_event(claims, plan_id, "ACTION_BLOCKED", "Connected-tool action blocked", "PBE stopped the action because input validation did not pass.", 35, (plan.get("plan") or {}).get("estimated_duration_minutes", 15), {"action_index": action_index, "tool_slug": slug})
        raise HTTPException(400,str(exc)) from exc
    except Exception as exc:
        _workflow_event(claims, plan_id, "ACTION_FAILED", "Connected-tool action failed", "The provider action did not complete successfully. Review logs and permissions before retrying.", 35, (plan.get("plan") or {}).get("estimated_duration_minutes", 15), {"action_index": action_index, "tool_slug": slug, "error_type": type(exc).__name__})
        log.exception("Composio action execution failed")
        raise HTTPException(502,"The connected tool action failed. Check the tool's permissions and action inputs.") from exc

@app.get("/api/state")
def state(claims=Depends(auth)):
    current=workspace_engine(claims).state()
    try:
        with db() as conn:
            event_rows=conn.execute("SELECT event_id,timestamp,source_vector,entity_context,payload_hash,anonymized_telemetry FROM uol_events WHERE tenant_id=%s AND workspace_id=%s ORDER BY timestamp DESC LIMIT 100",(claims["tenant_id"],claims["workspace_id"])).fetchall()
        if event_rows:
            current["events"]=[{"event_id":r[0],"timestamp":r[1].isoformat(),"source_vector":r[2],"entity_context":r[3],"payload_hash":r[4],"anonymized_telemetry":r[5]} for r in reversed(event_rows)]
    except Exception:
        log.exception("Could not hydrate persisted UOL state")
    try:
        from pbe.services.module_registry import list_modules
        persisted=list_modules(claims["tenant_id"],claims["workspace_id"])
        if persisted: current["modules"]=persisted
        current["active_count"]=sum(m["state"]=="ACTIVE" for m in current["modules"])
        current["staged_count"]=sum(m["state"]=="STAGED" for m in current["modules"])
        with db() as conn:
            rows=conn.execute("SELECT action,actor,detail,created_at FROM audit_events WHERE tenant_id=%s AND workspace_id=%s ORDER BY created_at DESC LIMIT 30",(claims["tenant_id"],claims["workspace_id"])).fetchall()
        if rows: current["audit"]=[{"action":r[0],"actor":r[1],"detail":json.dumps(r[2],default=str),"timestamp":r[3].isoformat()} for r in reversed(rows)]
    except Exception:
        log.exception("Could not hydrate persisted workspace state")
    return current

@app.post("/api/demo/inject")
async def inject(req:DemoEventRequest, claims=Depends(auth)):
    require_role(claims,"OWNER","ADMIN","MEMBER")
    safe_req=req.model_copy(update={"tenant_id":claims["tenant_id"]})
    e=workspace_engine(claims); event=e.ingest(safe_req)
    with db() as conn:
        conn.execute("INSERT INTO uol_events(event_id,tenant_id,workspace_id,timestamp,source_vector,entity_context,payload_hash,anonymized_telemetry,processing_status,processed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PROCESSED',now()) ON CONFLICT (event_id) DO NOTHING",(event.event_id,claims["tenant_id"],claims["workspace_id"],event.timestamp,event.source_vector.value,json.dumps(event.entity_context),event.payload_hash,event.anonymized_telemetry))
    result=await e.evolve(claims["tenant_id"],claims["workspace_id"])
    if result is None: return {"status":"no_action_required","event_id":event.event_id}
    return result.model_dump(mode="json")

@app.post("/api/modules/{module_id}/approve")
def approve(module_id:str, claims=Depends(auth)):
    require_role(claims,"OWNER","ADMIN")
    e=workspace_engine(claims)
    # Load the module from this workspace's persisted registry if this process restarted.
    if not any(m.module_id==module_id for m in e.modules):
        from pbe.services.module_registry import list_modules
        rows=list_modules(claims["tenant_id"],claims["workspace_id"])
        row=next((x for x in rows if x["module_id"]==module_id),None)
        if row and row["state"]=="STAGED":
            from pbe.core.schemas import GeneratedModule
            e.modules.append(GeneratedModule(module_id=row["module_id"],version=row["version"],name=row["name"],purpose=row["purpose"],state=row["state"],backend_python_router_code=row["backend_python_router_code"],frontend_json_layout_schema=row["frontend_json_layout_schema"],security_permission_manifest=row["security_permission_manifest"],generated_module_hash=row["generated_module_hash"],validation=row["validation"],source_event_ids=row["source_event_ids"],deployment_status=row.get("deployment_status","NOT_DEPLOYED")))
    try:return e.approve(module_id,claims["tenant_id"],claims["workspace_id"]).model_dump(mode="json")
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.post("/api/demo/failure")
async def failure(claims=Depends(auth)):
    require_role(claims,"OWNER","ADMIN")
    try:return (await workspace_engine(claims).failure(claims["tenant_id"],claims["workspace_id"])).model_dump(mode="json")
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.post("/api/demo/reset")
def reset(claims=Depends(auth)):
    require_role(claims,"OWNER","ADMIN")
    workspace_engine(claims).reset()
    # Reset only the prototype demo signal history and modules derived from those signals.
    # Real Composio/provider events and their modules are retained.
    with db() as conn:
        conn.execute("""DELETE FROM runtime_modules WHERE tenant_id=%s AND workspace_id=%s AND source_event_ids ?| ARRAY(SELECT event_id FROM uol_events WHERE tenant_id=%s AND workspace_id=%s AND source_vector='demo')""",(claims["tenant_id"],claims["workspace_id"],claims["tenant_id"],claims["workspace_id"]))
        conn.execute("DELETE FROM uol_events WHERE tenant_id=%s AND workspace_id=%s AND source_vector='demo'",(claims["tenant_id"],claims["workspace_id"]))
    return workspace_engine(claims).state()
