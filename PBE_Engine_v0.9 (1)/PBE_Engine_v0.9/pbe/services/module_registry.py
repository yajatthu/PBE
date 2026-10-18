import json
from pbe.db import db

def save_module(module, tenant_id: str, workspace_id: str|None):
    with db() as conn:
        conn.execute("""INSERT INTO runtime_modules(module_id,tenant_id,workspace_id,version,name,purpose,state,generated_module_hash,backend_source,frontend_schema,permission_manifest,validation,source_event_ids,deployment_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(module_id) DO UPDATE SET state=EXCLUDED.state, validation=EXCLUDED.validation, deployment_status=EXCLUDED.deployment_status""", (module.module_id,tenant_id,workspace_id,module.version,module.name,module.purpose,module.state.value,module.generated_module_hash,module.backend_python_router_code,json.dumps(module.frontend_json_layout_schema),json.dumps(module.security_permission_manifest),json.dumps(module.validation),json.dumps(module.source_event_ids),getattr(module,"deployment_status","NOT_DEPLOYED")))

def set_state(module_id: str, state: str, tenant_id: str|None=None, workspace_id: str|None=None, deployment_status: str|None=None):
    with db() as conn:
        clauses=["module_id=%s"]; params=[state]
        if deployment_status is not None:
            sql="UPDATE runtime_modules SET state=%s, deployment_status=%s WHERE module_id=%s"; params=[state,deployment_status,module_id]
        else: sql="UPDATE runtime_modules SET state=%s WHERE module_id=%s"
        if tenant_id is not None: sql += " AND tenant_id=%s"; params.append(tenant_id)
        if workspace_id is not None: sql += " AND workspace_id=%s"; params.append(workspace_id)
        cur=conn.execute(sql,tuple(params))
        if cur.rowcount != 1: raise ValueError("Module not found in the current tenant/workspace")

def list_modules(tenant_id: str, workspace_id: str):
    with db() as conn:
        rows=conn.execute("SELECT module_id,version,name,purpose,state,backend_source,frontend_schema,permission_manifest,generated_module_hash,validation,source_event_ids,created_at,deployment_status FROM runtime_modules WHERE tenant_id=%s AND workspace_id=%s ORDER BY created_at ASC",(tenant_id,workspace_id)).fetchall()
    result=[]
    for r in rows:
        result.append({"module_id":r[0],"version":r[1],"name":r[2],"purpose":r[3],"state":r[4],"backend_python_router_code":r[5],"frontend_json_layout_schema":r[6],"security_permission_manifest":r[7],"generated_module_hash":r[8],"validation":r[9],"source_event_ids":r[10],"created_at":r[11].isoformat() if r[11] else None,"deployment_status":r[12]})
    return result


def next_version(tenant_id: str, workspace_id: str, name: str) -> int:
    with db() as conn:
        row=conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM runtime_modules WHERE tenant_id=%s AND name=%s",(tenant_id,name)).fetchone()
    return int(row[0])
