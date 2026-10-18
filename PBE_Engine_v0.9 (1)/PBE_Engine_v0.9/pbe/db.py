from contextlib import contextmanager
from pathlib import Path
import logging
import psycopg
from pbe.settings import settings

log = logging.getLogger(__name__)

@contextmanager
def db():
    with psycopg.connect(settings.DATABASE_URL) as conn:
        yield conn
        conn.commit()

def init_db():
    """Check DB readiness; optionally apply the idempotent bundled schema."""
    with db() as conn:
        if settings.PBE_AUTO_INIT_SCHEMA:
            schema_path = Path(__file__).resolve().parent.parent / "infra" / "postgres" / "init.sql"
            if not schema_path.exists():
                raise RuntimeError(f"PBE_AUTO_INIT_SCHEMA is enabled but schema file is missing: {schema_path}")
            # All statements in this project schema are idempotent CREATE/ALTER statements.
            script = schema_path.read_text(encoding="utf-8")
            for statement in script.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(statement)
        row = conn.execute("SELECT to_regclass('public.users'), to_regclass('public.runtime_modules'), to_regclass('public.uol_events')").fetchone()
        missing = [name for name, value in zip(("users", "runtime_modules", "uol_events"), row) if value is None]
        if missing:
            raise RuntimeError("PBE database schema is missing required tables: " + ", ".join(missing) + ". Apply infra/postgres/init.sql or set PBE_AUTO_INIT_SCHEMA=true where database permissions allow it.")
        # Additive, idempotent migrations for existing v0.4 databases.
        conn.execute("ALTER TABLE uol_events ADD COLUMN IF NOT EXISTS processing_status TEXT NOT NULL DEFAULT 'PENDING'")
        conn.execute("ALTER TABLE uol_events ADD COLUMN IF NOT EXISTS processing_error TEXT")
        conn.execute("ALTER TABLE uol_events ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ")
        conn.execute("ALTER TABLE runtime_modules ADD COLUMN IF NOT EXISTS deployment_status TEXT NOT NULL DEFAULT 'NOT_DEPLOYED'")
        # v0.6 additions are idempotent and keep the existing engine tables intact.
        conn.execute("CREATE TABLE IF NOT EXISTS saas_plans (id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, objective TEXT NOT NULL, services JSONB NOT NULL DEFAULT '[]'::jsonb, plan JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'PLANNED' CHECK (status IN ('PLANNED','APPROVED','IN_PROGRESS','COMPLETED','BLOCKED')), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        conn.execute("CREATE TABLE IF NOT EXISTS saas_plan_executions (id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, plan_id UUID NOT NULL REFERENCES saas_plans(id) ON DELETE CASCADE, action_index INTEGER NOT NULL, result JSONB NOT NULL DEFAULT '{}'::jsonb, status TEXT NOT NULL DEFAULT 'RECORDED', created_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_saas_plans_workspace_time ON saas_plans(tenant_id,workspace_id,created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_saas_plan_executions_plan ON saas_plan_executions(tenant_id,workspace_id,plan_id,created_at)")
        # v0.9 durable workflow timeline. All reads are scoped by tenant + workspace.
        conn.execute("""CREATE TABLE IF NOT EXISTS workflow_timeline_events (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            plan_id UUID NOT NULL REFERENCES saas_plans(id) ON DELETE CASCADE,
            actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            progress INTEGER CHECK (progress IS NULL OR (progress >= 0 AND progress <= 100)),
            expected_minutes INTEGER CHECK (expected_minutes IS NULL OR expected_minutes >= 0),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_timeline_plan ON workflow_timeline_events(tenant_id,workspace_id,plan_id,created_at)")
