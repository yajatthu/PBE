import json
from pbe.core.schemas import PMInput, PMOutput
from pbe.services.openrouter import OpenRouterClient

class PMAgent:
    async def reason(self, inp: PMInput) -> PMOutput:
        client = OpenRouterClient()
        if client.enabled:
            raw = await client.chat(
                "You are PBE's Cognitive Arbiter. Return only valid JSON matching PMOutput. Identify an execution gap and design a narrow internal capability.",
                json.dumps(inp.model_dump(mode="json")),
            )
            return PMOutput.model_validate(json.loads(raw))
        latest = inp.rolling_log_context[-1] if inp.rolling_log_context else None
        raw_goal = (latest.anonymized_telemetry if latest else "")
        goal = raw_goal.split(":", 1)[1].strip() if ":" in raw_goal else raw_goal.strip()
        goal = goal[:500] or "Define and validate the user's requested internal business capability."
        spec = {
            "functional_objective": f"PBE capability intake for: {goal[:180]}",
            "user_goal": goal,
            "prototype_boundary": "This fallback produces an intake scaffold, not a complete SaaS replacement.",
            "sql_migrations": [],
            "backend_endpoints": [
                {"path": "/generated/capability-intake", "method": "GET", "payload_contract": "returns the requested capability goal and explicitly marks the scaffold as not production-ready"},
            ],
            "frontend": {"component_type": "CapabilityIntakeWorkspace", "label": "Capability Intake", "data_source_endpoint": "/generated/capability-intake"},
            "affected_systems": ["requested business workflow"],
            "acceptance_criteria": ["Confirm required inputs and outputs", "Implement the actual workflow", "Validate permissions and data migration", "Run acceptance tests before replacing an external service"],
            "approval_reason": "This is a context-specific prototype scaffold. It must be implemented and validated before it can replace an external service.",
        }
        return PMOutput(
            action_required=True,
            architectural_reasoning="The request describes a capability gap. PBE should create a narrow internal capability proposal and validate it before replacing any external service.",
            target_specification_document=spec,
        )
