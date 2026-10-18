import json
from uuid import uuid4
from pbe.db import db

def create_plan(tenant_id, workspace_id, user_id, objective, services, plan):
    plan_id = str(uuid4())
    with db() as conn:
        row = conn.execute("INSERT INTO saas_plans(id,tenant_id,workspace_id,user_id,objective,services,plan,status) VALUES (%s,%s,%s,%s,%s,%s,%s,'PLANNED') RETURNING created_at", (plan_id,tenant_id,workspace_id,user_id,objective,json.dumps(services),json.dumps(plan))).fetchone()
    return {"id":plan_id,"objective":objective,"services":services,"plan":plan,"status":"PLANNED","created_at":row[0].isoformat() if row and row[0] else None}

def list_plans(tenant_id, workspace_id, limit=20):
    limit=max(1,min(int(limit),100))
    with db() as conn:
        rows=conn.execute("SELECT id,objective,services,plan,status,created_at FROM saas_plans WHERE tenant_id=%s AND workspace_id=%s ORDER BY created_at DESC LIMIT %s",(tenant_id,workspace_id,limit)).fetchall()
    return [{"id":str(r[0]),"objective":r[1],"services":r[2],"plan":r[3],"status":r[4],"created_at":r[5].isoformat()} for r in rows]

def get_plan(tenant_id, workspace_id, plan_id):
    with db() as conn:
        r=conn.execute("SELECT id,objective,services,plan,status,created_at FROM saas_plans WHERE tenant_id=%s AND workspace_id=%s AND id=%s",(tenant_id,workspace_id,plan_id)).fetchone()
    if not r: return None
    return {"id":str(r[0]),"objective":r[1],"services":r[2],"plan":r[3],"status":r[4],"created_at":r[5].isoformat()}

def set_plan_status(tenant_id, workspace_id, plan_id, status):
    with db() as conn:
        r=conn.execute("UPDATE saas_plans SET status=%s,updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND id=%s RETURNING id",(status,tenant_id,workspace_id,plan_id)).fetchone()
    return bool(r)

def get_action_execution(tenant_id, workspace_id, plan_id, action_index):
    with db() as conn:
        row=conn.execute("SELECT status,result,created_at FROM saas_plan_executions WHERE tenant_id=%s AND workspace_id=%s AND plan_id=%s AND action_index=%s ORDER BY created_at DESC LIMIT 1",(tenant_id,workspace_id,plan_id,action_index)).fetchone()
    if not row: return None
    return {"status":row[0],"result":row[1],"created_at":row[2].isoformat()}

def save_execution(tenant_id, workspace_id, plan_id, action_index, result, status="SUCCEEDED"):
    with db() as conn:
        conn.execute("INSERT INTO saas_plan_executions(id,tenant_id,workspace_id,plan_id,action_index,result,status) VALUES (%s,%s,%s,%s,%s,%s,%s)",(str(uuid4()),tenant_id,workspace_id,plan_id,action_index,json.dumps(result),status))
        conn.execute("UPDATE saas_plans SET updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND id=%s",(tenant_id,workspace_id,plan_id))

def list_executions(tenant_id, workspace_id, plan_id):
    with db() as conn:
        rows=conn.execute("SELECT action_index,result,status,created_at FROM saas_plan_executions WHERE tenant_id=%s AND workspace_id=%s AND plan_id=%s ORDER BY created_at",(tenant_id,workspace_id,plan_id)).fetchall()
    return [{"action_index":r[0],"result":r[1],"status":r[2],"created_at":r[3].isoformat()} for r in rows]

def update_plan_document(tenant_id, workspace_id, plan_id, plan_document):
    with db() as conn:
        row=conn.execute("UPDATE saas_plans SET plan=%s,updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND id=%s RETURNING id",(json.dumps(plan_document),tenant_id,workspace_id,plan_id)).fetchone()
    return bool(row)
