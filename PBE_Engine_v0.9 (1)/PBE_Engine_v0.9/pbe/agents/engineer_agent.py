import hashlib, json
from uuid import uuid4
from pbe.core.schemas import EngineerInput, GeneratedModule, DeploymentState
from pbe.services.openrouter import OpenRouterClient
class EngineerAgent:
    async def compile(self, inp: EngineerInput, version: int=1) -> GeneratedModule:
        client=OpenRouterClient(); spec=inp.specification_document
        if client.enabled:
            raw=await client.chat("You are PBE's Compilation Engineer. Return JSON containing name,purpose,backend_python_router_code,frontend_json_layout_schema,security_permission_manifest. Keep generated code narrow and safe.",json.dumps(inp.model_dump(mode="json")))
            data=json.loads(raw)
        else:
            # Context-aware fallback: create a clearly labeled intake scaffold rather than
            # pretending every request is a subscription-management application.
            objective=str(spec.get("functional_objective") or "PBE capability intake")[:180]
            purpose=str(spec.get("prototype_boundary") or "Prototype scaffold only; implement and validate before production use.")[:500]
            safe_objective=json.dumps(objective)
            data={
                "name": objective[:100],
                "purpose": purpose,
                "backend_python_router_code": (
                    "from fastapi import APIRouter\n"
                    "router=APIRouter(prefix='/generated/capability-intake', tags=['generated'])\n"
                    "@router.get('')\n"
                    "def capability_intake():\n"
                    f"    return {{'objective': {safe_objective}, 'status': 'PROTOTYPE_SCAFFOLD_NOT_A_REPLACEMENT', 'items': []}}\n"
                ),
                "frontend_json_layout_schema": {
                    "type":"WorkspaceComponent","version":1,
                    "elements":[
                        {"type":"MetricWidget","props":{"card_title":"Prototype scaffold","value":"NOT A REPLACEMENT","description":"Implement and test before replacing the external service."}},
                        {"type":"DataGridTable","props":{"card_title":"Acceptance checklist","items":spec.get("acceptance_criteria",["Implement workflow","Validate outputs","Test with real users"])}},
                    ],
                },
                "security_permission_manifest": {
                    "default":"DENY","allowed_db_tables":[],"allowed_external_endpoints":[],
                    "signed_clearance":"PBE-PROTOTYPE-INTAKE-ONLY",
                },
            }

        src=data["backend_python_router_code"]+json.dumps(data["frontend_json_layout_schema"],sort_keys=True)+json.dumps(data["security_permission_manifest"],sort_keys=True)
        h=hashlib.sha256(src.encode()).hexdigest()
        return GeneratedModule(module_id=f"mod_{uuid4().hex[:12]}",version=version,name=data["name"],purpose=data["purpose"],state=DeploymentState.COMPILED,backend_python_router_code=data["backend_python_router_code"],frontend_json_layout_schema=data["frontend_json_layout_schema"],security_permission_manifest=data["security_permission_manifest"],generated_module_hash=h,source_event_ids=inp.specification_document.get("source_event_ids",[]),reasoning=inp.specification_document.get("reasoning", ""))
