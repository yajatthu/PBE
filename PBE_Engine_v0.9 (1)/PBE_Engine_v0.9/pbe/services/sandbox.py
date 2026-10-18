import ast, os, subprocess, tempfile
from pbe.settings import settings

ALLOWED_UI = {"MetricWidget", "FormContainer", "DataGridTable", "AssetDownloader"}
ALLOWED_IMPORT_ROOTS = {"fastapi", "pydantic", "typing", "datetime", "uuid", "decimal", "enum", "json", "dataclasses"}
DENIED_IMPORT_ROOTS = {"os", "subprocess", "socket", "ctypes", "pty", "pathlib", "shutil", "multiprocessing", "threading", "importlib", "pickle", "marshal", "sys", "signal", "resource"}
DENIED_CALLS = {"exec", "eval", "compile", "__import__", "open", "input", "breakpoint", "globals", "locals", "vars", "getattr", "setattr", "delattr"}


def _static_validate(code: str):
    tests = []
    if not isinstance(code, str) or len(code.encode("utf-8")) > settings.PBE_MAX_GENERATED_SOURCE_BYTES:
        return [("source_size", "FAIL", "Generated source is missing or exceeds configured limit")]
    try:
        tree = ast.parse(code)
        tests.append(("python_syntax", "PASS", "AST parse succeeded"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module.split(".")[0])
        denied = sorted(set(imports) & DENIED_IMPORT_ROOTS)
        unsupported = sorted(set(imports) - ALLOWED_IMPORT_ROOTS)
        bad_imports = sorted(set(denied + unsupported))
        tests.append(("import_policy", "FAIL" if bad_imports else "PASS", f"Imports not allowed by static policy: {bad_imports}" if bad_imports else "Imports passed allowlist"))
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in DENIED_CALLS:
                    calls.append(node.func.id)
                elif isinstance(node.func, ast.Attribute) and node.func.attr in {"system", "popen", "spawn", "fork", "remove", "unlink", "rmdir", "write_text", "write_bytes"}:
                    calls.append(node.func.attr)
        calls = sorted(set(calls))
        tests.append(("dangerous_calls", "FAIL" if calls else "PASS", f"Blocked calls: {calls}" if calls else "No blocked call nodes detected"))
    except Exception as e:
        tests.append(("python_syntax", "FAIL", f"Parse/AST inspection failed: {type(e).__name__}"))
    return tests


def validate(module):
    tests = _static_validate(module.backend_python_router_code)
    schema = module.frontend_json_layout_schema
    elems = schema.get("elements", []) if isinstance(schema, dict) else None
    if not isinstance(elems, list) or len(elems) > 50:
        tests.append(("dynamic_ui_registry", "FAIL", "UI schema must contain an elements list with at most 50 components"))
    else:
        bad = [e.get("type") for e in elems if not isinstance(e, dict) or e.get("type") not in ALLOWED_UI]
        tests.append(("dynamic_ui_registry", "FAIL" if bad else "PASS", f"Unknown or malformed components: {bad}" if bad else f"{len(elems)} registered components accepted"))
    manifest = module.security_permission_manifest
    manifest_ok = isinstance(manifest, dict) and manifest.get("default") == "DENY" and isinstance(manifest.get("allowed_db_tables", []), list) and isinstance(manifest.get("allowed_external_endpoints", []), list)
    tests.append(("deny_by_default", "PASS" if manifest_ok else "FAIL", "Permission manifest uses deny-by-default" if manifest_ok else "Permission manifest is malformed or not deny-by-default"))
    if settings.PBE_SANDBOX_ENABLED:
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "generated_module.py")
            with open(src, "w", encoding="utf-8") as f: f.write(module.backend_python_router_code)
            cmd = ["podman", "run", "--rm", "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=64", "--memory=256m", "--cpus=0.5", "-v", f"{d}:/workspace:ro", settings.PBE_SANDBOX_IMAGE, "python", "-m", "py_compile", "/workspace/generated_module.py"]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.PBE_SANDBOX_TIMEOUT_SECONDS)
                tests.append(("podman_sandbox_compile", "PASS" if r.returncode == 0 else "FAIL", (r.stdout.strip() or r.stderr.strip())[:1000]))
            except Exception as e:
                tests.append(("podman_sandbox_compile", "FAIL", f"Sandbox unavailable/failed: {type(e).__name__}"))
    else:
        tests.append(("podman_sandbox_compile", "SKIP", "PBE_SANDBOX_ENABLED=false; static validation only; generated code must not be executed"))
    passed = sum(t[1] == "PASS" for t in tests)
    hard_fail = any(t[1] == "FAIL" for t in tests)
    return not hard_fail, {"tests": [{"name": a, "status": b, "detail": c} for a,b,c in tests], "passed": passed, "total": len(tests), "sandbox_mode": "ephemeral Podman compile sandbox" if settings.PBE_SANDBOX_ENABLED else "static validation only; no generated-code execution"}
