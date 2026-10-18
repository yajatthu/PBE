import pytest
from pbe.integrations.tool_contracts import (
    normalize_tool, normalize_account_items, unwrap_list,
    validate_tool_arguments, safe_slug,
)

def test_normalize_tool_common_composio_shape():
    tool = normalize_tool({
        "slug": "CANVA_CREATE_DESIGN",
        "name": "Create design",
        "toolkit": {"slug": "canva", "name": "Canva"},
        "input_parameters": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
    })
    assert tool["slug"] == "CANVA_CREATE_DESIGN"
    assert tool["toolkit"] == "canva"
    assert "properties" in tool["input_schema"]

def test_unwrap_nested_tool_list():
    assert unwrap_list({"data": {"items": [{"slug": "X"}]}}, ("items", "data")) == [{"slug": "X"}]

def test_normalize_account_envelope_and_nested_toolkit():
    rows = normalize_account_items({"items": [{"id": "acct-1", "user_id": "u1", "toolkit": {"slug": "figma"}}]})
    assert rows == [{"id": "acct-1", "toolkit": "figma", "owner": "u1", "name": "figma", "status": "UNKNOWN"}]

def test_validate_json_schema_required_and_extra():
    schema = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"], "additionalProperties": False}
    validate_tool_arguments({"title": "hello"}, schema)
    with pytest.raises(ValueError, match="Missing required"):
        validate_tool_arguments({}, schema)
    with pytest.raises(ValueError, match="Unknown tool argument"):
        validate_tool_arguments({"title": "hello", "danger": True}, schema)

def test_validate_composio_flat_parameters():
    schema = {"title": {"type": "string", "required": True}, "description": {"type": "string"}}
    validate_tool_arguments({"title": "Campaign"}, schema)
    with pytest.raises(ValueError, match="missing required"):
        validate_tool_arguments({}, schema)

def test_safe_slug_rejects_injection_like_identifiers():
    assert safe_slug("CANVA_CREATE_DESIGN") == "CANVA_CREATE_DESIGN"
    assert safe_slug("../../etc/passwd") is None
    assert safe_slug("CANVA/../EXECUTE") is None
    assert safe_slug("bad slug") is None

@pytest.mark.asyncio
async def test_no_key_agent_fallback_is_contextual_and_passes_registry_policy(monkeypatch):
    from pbe.settings import settings
    from pbe.core.schemas import PMInput, UOLEvent, SourceVector, EngineerInput
    from pbe.agents.pm_agent import PMAgent
    from pbe.agents.engineer_agent import EngineerAgent
    from pbe.services.sandbox import validate
    from datetime import datetime, timezone
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    event=UOLEvent(event_id="test-event",timestamp=datetime.now(timezone.utc),source_vector=SourceVector.demo,entity_context={},payload_hash="sha256_test",anonymized_telemetry="customer_request:Build a brand asset approval tracker")
    pm=await PMAgent().reason(PMInput(tenant_id="tenant",rolling_log_context=[event],active_database_schema_graph={}))
    assert "brand asset approval tracker" in pm.target_specification_document["user_goal"]
    module=await EngineerAgent().compile(EngineerInput(tenant_id="tenant",specification_document={**pm.target_specification_document,"source_event_ids":[event.event_id]}))
    assert "PROTOTYPE_SCAFFOLD_NOT_A_REPLACEMENT" in module.backend_python_router_code
    ok, report=validate(module)
    assert ok, report
