"""Normalize Composio V3 response envelopes and validate proposed tool inputs."""
from __future__ import annotations
import re
from typing import Any

_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$")

def safe_slug(value: Any) -> str | None:
    if not isinstance(value, str): return None
    value=value.strip()
    return value if _SLUG.fullmatch(value) else None

def _toolkit(value: Any, fallback: str = "unknown") -> str:
    if isinstance(value, dict):
        value=value.get("slug") or value.get("name") or value.get("toolkit_slug")
    if not isinstance(value, str) or not value.strip(): return fallback
    return value.strip().lower()

def unwrap_list(data: Any, keys: tuple[str,...]) -> list[dict]:
    """Unwrap common list envelopes without accidentally treating metadata as items."""
    if isinstance(data, list): return [x for x in data if isinstance(x,dict)]
    if not isinstance(data,dict): return []
    for key in keys:
        value=data.get(key)
        if isinstance(value,list): return [x for x in value if isinstance(x,dict)]
        if isinstance(value,dict):
            nested=unwrap_list(value, keys)
            if nested: return nested
    return []

def normalize_tool(item: dict, fallback_toolkit: str = "unknown") -> dict | None:
    slug=safe_slug(item.get("slug") or item.get("tool_slug") or item.get("name") or item.get("toolSlug"))
    if not slug: return None
    toolkit=_toolkit(item.get("toolkit") or item.get("toolkit_slug") or item.get("app") or item.get("integration"),fallback_toolkit)
    schema=item.get("input_parameters") or item.get("parameters") or item.get("input_schema") or item.get("inputSchema") or {}
    if not isinstance(schema,dict): schema={}
    return {"slug":slug,"name":str(item.get("name") or item.get("display_name") or slug)[:180],"description":str(item.get("description") or "")[:500],"toolkit":toolkit,"input_schema":schema,"version":str(item.get("version") or "latest")}

def normalize_account_items(data: Any) -> list[dict]:
    rows=unwrap_list(data,("items","connected_accounts","connectedAccounts","accounts","data","results"))
    # Some API responses wrap one account under data rather than a list.
    if not rows and isinstance(data,dict):
        candidate=data.get("data")
        if isinstance(candidate,dict) and (candidate.get("id") or candidate.get("connected_account_id")): rows=[candidate]
    out=[]; seen=set()
    for row in rows:
        aid=row.get("id") or row.get("connected_account_id") or row.get("connectedAccountId")
        if not aid or str(aid) in seen: continue
        tk=_toolkit(row.get("toolkit") or row.get("toolkit_slug") or row.get("app") or row.get("integration") or row.get("integration_name"),"")
        if not tk:
            # Some responses expose toolkit metadata under a nested app object.
            tk=_toolkit(row.get("app_info") or row.get("toolkit_info"),"")
        owner=row.get("user_id") or row.get("userId") or row.get("user_id_external")
        out.append({"id":str(aid),"toolkit":tk,"owner":str(owner) if owner is not None else None,"name":str(row.get("name") or row.get("display_name") or tk or "Connected account")[:180],"status":str(row.get("status") or row.get("state") or "UNKNOWN").upper()})
        seen.add(str(aid))
    return out

def validate_tool_arguments(arguments: Any, schema: Any) -> None:
    """Validate required/unknown fields across both JSON Schema and Composio parameter maps."""
    if not isinstance(arguments,dict): raise ValueError("Tool arguments must be a JSON object")
    if not isinstance(schema,dict) or not schema: return
    # Full JSON Schema form: {type: object, properties: {...}, required: [...]}.
    properties=schema.get("properties") if isinstance(schema.get("properties"),dict) else None
    if properties is not None:
        required=schema.get("required",[])
        if isinstance(required,list):
            missing=[str(k) for k in required if k not in arguments]
            if missing: raise ValueError("Missing required tool argument(s): "+", ".join(missing))
        if schema.get("additionalProperties") is False:
            extra=set(arguments)-set(properties)
            if extra: raise ValueError("Unknown tool argument(s): "+", ".join(sorted(extra)))
        return
    # Composio sometimes returns a flat property map or a list of parameter objects.
    if isinstance(schema.get("parameters"),list):
        params={str(x.get("name")):x for x in schema["parameters"] if isinstance(x,dict) and x.get("name")}
    else:
        params={k:v for k,v in schema.items() if isinstance(v,dict) and k not in {"properties","required"}}
    if not params: return
    extra=set(arguments)-set(params)
    required={k for k,v in params.items() if v.get("required") is True}
    missing=required-set(arguments)
    if extra or missing:
        bits=[]
        if missing: bits.append("missing required: "+", ".join(sorted(missing)))
        if extra: bits.append("unknown: "+", ".join(sorted(extra)))
        raise ValueError("Tool arguments do not match the current input schema ("+"; ".join(bits)+")")
