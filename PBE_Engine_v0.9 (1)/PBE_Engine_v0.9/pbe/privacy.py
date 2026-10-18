import re

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*")
SECRET_RE = re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*[:=]\s*[^\s,;]+")

def redact_sensitive(value):
    if isinstance(value, dict):
        out={}
        for k,v in value.items():
            if re.search(r"(?i)(password|secret|token|api.?key|authorization|credential)", str(k)):
                out[str(k)]="[REDACTED]"
            else: out[str(k)]=redact_sensitive(v)
        return out
    if isinstance(value, list): return [redact_sensitive(v) for v in value[:500]]
    if isinstance(value, str):
        value=EMAIL_RE.sub("[REDACTED_EMAIL]", value)
        value=BEARER_RE.sub("Bearer [REDACTED]", value)
        return SECRET_RE.sub(lambda m: m.group(1)+"=[REDACTED]", value)[:4000]
    if value is None or isinstance(value,(int,float,bool)): return value
    return str(value)[:500]
