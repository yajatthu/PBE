from types import SimpleNamespace
from pbe.services.sandbox import _static_validate, validate
from pbe.privacy import redact_sensitive


def test_static_validator_accepts_narrow_fastapi_router():
    code = "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/')\ndef read_items():\n    return {'items': []}\n"
    results = _static_validate(code)
    assert all(status != "FAIL" for _, status, _ in results), results


def test_static_validator_rejects_dangerous_import_and_call():
    code = "import subprocess\nsubprocess.run(['whoami'])\n"
    results = _static_validate(code)
    assert any(status == "FAIL" for _, status, _ in results)


def test_validator_rejects_non_deny_by_default_manifest():
    module = SimpleNamespace(
        backend_python_router_code="from fastapi import APIRouter\nrouter=APIRouter()",
        frontend_json_layout_schema={"elements": [{"type": "MetricWidget"}]},
        security_permission_manifest={"default": "ALLOW"},
    )
    ok, report = validate(module)
    assert not ok
    assert any(t["name"] == "deny_by_default" and t["status"] == "FAIL" for t in report["tests"])


def test_redacts_common_sensitive_fields():
    value = redact_sensitive({"email": "person@example.com", "api_key": "abc123", "note": "Bearer abc.def"})
    assert value["api_key"] == "[REDACTED]"
    assert "[REDACTED_EMAIL]" in value["email"]
    assert "[REDACTED]" in value["note"]
