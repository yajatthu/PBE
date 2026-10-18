import json
from pbe.db import db

def record(tenant_id: str|None, workspace_id: str|None, actor: str, action: str, detail: dict):
    with db() as conn:
        conn.execute("INSERT INTO audit_events(tenant_id,workspace_id,actor,action,detail) VALUES (%s,%s,%s,%s,%s)", (tenant_id, workspace_id, actor, action, json.dumps(detail)))
