"""Simple, investor-demo planner for capability discovery and SaaS replacement.

It does not scrape proprietary SaaS internals or claim to clone them automatically.
It turns a user's goal into a scoped capability plan, tool actions, and PBE-native
modules that the existing Observation-to-Code pipeline can later build and validate.
"""
import json
from pydantic import BaseModel, Field, ValidationError
from pbe.services.openrouter import OpenRouterClient

class ToolAction(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    toolkit: str = Field(min_length=1, max_length=80)
    tool_slug: str = Field(min_length=1, max_length=180)
    purpose: str = Field(min_length=1, max_length=500)
    arguments: dict = Field(default_factory=dict)
    requires_human_approval: bool = True

class NativeCapability(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    replaces: str = Field(min_length=1, max_length=160)
    capability: str = Field(min_length=1, max_length=700)
    implementation_steps: list[str] = Field(default_factory=list, max_length=8)
    readiness: str = "PROPOSED"
    subscription_cancel_gate: list[str] = Field(default_factory=list, max_length=8)

class SaaSPlan(BaseModel):
    title: str
    objective_summary: str
    capabilities_observed: list[str] = Field(default_factory=list, max_length=10)
    tool_actions: list[ToolAction] = Field(default_factory=list, max_length=12)
    native_capabilities: list[NativeCapability] = Field(default_factory=list, max_length=8)
    savings_logic: str
    limitations: list[str] = Field(default_factory=list, max_length=8)
    next_question: str = ""
    estimated_duration_minutes: int = Field(default=15, ge=1, le=10080)
    workflow_steps: list[dict] = Field(default_factory=list, max_length=12)

SYSTEM = '''You are the PBE Capability Architect. PBE's mission is to reduce dependency on external SaaS by learning the business outcome a user needs, orchestrating authorized tools, and proposing/building PBE-native alternatives through its existing Observation-to-Code architecture. Return one JSON object matching SaaSPlan fields.

Rules:
- Include estimated_duration_minutes as a realistic estimate for this requested workflow (1-10080 minutes), not a guarantee.
- Include workflow_steps as ordered objects with keys: title, description, estimated_minutes, status. Use a concise timeline from connection/permission checks through execution and final review.
- Make the plan understandable to a 15-year-old; use plain language, short steps, no jargon unless explained.
- Do not claim you can inspect private internals of Canva/Figma/Notion or reproduce proprietary source code. Infer capabilities only from the user's stated needs and available tool descriptions.
- Use Composio actions only for tasks the connected tool actually supports. Tool slugs must be taken from the supplied available-tool list; if no list is supplied, return no executable tool_actions and ask the user to connect/choose tools.
- Propose narrow PBE-native capabilities for the repeated useful work the user wants to replace. Explain which external capability each proposal could replace, what must be built/tested, and the gate before canceling the paid service.
- Never recommend cancelling a subscription until the PBE replacement has passed acceptance tests, data export/migration, permission checks, and a real user trial. This is a safety gate, not a change to PBE's mission.
- Do not make up guaranteed savings or claim any subscription is already replaced. Label all native capabilities PROPOSED until implemented and validated.
- Keep tool actions minimal, with arguments explicit and non-destructive by default. Set requires_human_approval true for all actions.
- Return valid JSON only. Fields: title, objective_summary, capabilities_observed, tool_actions, native_capabilities, savings_logic, limitations, next_question.'''

async def make_plan(objective: str, services: list[str], available_tools: list[dict], current_modules: list[dict]):
    client = OpenRouterClient()
    payload = {
        "user_goal": objective,
        "connected_services_selected_by_user": services,
        "available_composio_tools": available_tools[:100],
        "existing_pbe_modules": [{"name":m.get("name"),"purpose":m.get("purpose"),"state":m.get("state")} for m in current_modules[:30]],
        "required_output": SaaSPlan.model_json_schema(),
    }
    if client.enabled:
        raw = await client.chat(SYSTEM, json.dumps(payload, ensure_ascii=False))
        try:
            plan = SaaSPlan.model_validate(json.loads(raw))
        except (ValueError, ValidationError) as exc:
            raise RuntimeError("The AI planner returned an invalid plan. Try a shorter goal or another configured model.") from exc
        # Defense in depth: only allow exact slugs supplied by Composio tool discovery.
        allowed = {str(x.get("slug") or x.get("tool_slug") or x.get("name") or "") for x in available_tools}
        plan.tool_actions = [a for a in plan.tool_actions if a.tool_slug in allowed]
        return plan.model_dump(mode="json")
    # Useful investor demo fallback: honest, visibly rule-based rather than pretending to use AI.
    target = services[0] if services else "the external SaaS tool"
    return SaaSPlan(
        title="Capability replacement plan",
        objective_summary=f"Break down the work you need from {target}, then replace repeatable parts with PBE-native capabilities.",
        capabilities_observed=["The user's desired outcome", "The selected external service(s)", "Current PBE module registry"],
        tool_actions=[],
        native_capabilities=[NativeCapability(name="PBE-native workflow workspace", replaces=target, capability="A focused workspace for the exact repeated workflow described by the user, without copying proprietary code.", implementation_steps=["Confirm the workflow and required inputs", "Use PBE Observation-to-Code to generate a narrow module", "Validate permissions, data migration, and outputs", "Run alongside the existing tool until accepted"], subscription_cancel_gate=["Required features pass agreed acceptance tests", "Data export and migration verified", "User completes a real trial without the paid tool", "No hidden dependency remains"])],
        savings_logic="Potential savings equal the subscription cost actually avoided minus PBE hosting, model, integration, storage, and maintenance costs. No savings are assumed until a replacement is proven.",
        limitations=["OpenRouter is not configured, so this is a template plan rather than an AI-generated analysis.", "No executable Composio tools were discovered for this request."],
        next_question="Which exact repeated task do you want PBE to replace first?",
        estimated_duration_minutes=20,
        workflow_steps=[
            {"title":"Confirm objective and scope","description":"Confirm the intended outcome and selected services.","estimated_minutes":2,"status":"READY"},
            {"title":"Check connected tools and permissions","description":"Verify available actions and account access.","estimated_minutes":4,"status":"PENDING"},
            {"title":"Execute approved actions","description":"Run each supported action only after explicit confirmation.","estimated_minutes":8,"status":"PENDING"},
            {"title":"Final review","description":"Review execution records and flag any checks that need human verification.","estimated_minutes":6,"status":"PENDING"}
        ]
    ).model_dump(mode="json")
