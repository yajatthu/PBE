CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY, name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS workspaces (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS memberships (
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, role TEXT NOT NULL CHECK (role IN ('OWNER','ADMIN','MEMBER','VIEWER')), PRIMARY KEY(user_id, workspace_id)
);
CREATE TABLE IF NOT EXISTS connected_accounts (
  id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, toolkit TEXT NOT NULL, composio_account_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(workspace_id, composio_account_id)
);
CREATE TABLE IF NOT EXISTS uol_events (
  event_id TEXT PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL, timestamp TIMESTAMPTZ NOT NULL, source_vector TEXT NOT NULL, entity_context JSONB NOT NULL, payload_hash TEXT NOT NULL, anonymized_telemetry TEXT NOT NULL, raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb, processing_status TEXT NOT NULL DEFAULT 'PENDING', processing_error TEXT, processed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE uol_events ADD COLUMN IF NOT EXISTS processing_status TEXT NOT NULL DEFAULT 'PENDING';
ALTER TABLE uol_events ADD COLUMN IF NOT EXISTS processing_error TEXT;
ALTER TABLE uol_events ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;
CREATE TABLE IF NOT EXISTS semantic_memory (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, content TEXT NOT NULL, metadata JSONB NOT NULL DEFAULT '{}'::jsonb, embedding vector(1536), created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS runtime_modules (
  module_id TEXT PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL, version INTEGER NOT NULL, name TEXT NOT NULL, purpose TEXT NOT NULL, state TEXT NOT NULL, generated_module_hash TEXT NOT NULL, backend_source TEXT NOT NULL, frontend_schema JSONB NOT NULL, permission_manifest JSONB NOT NULL, validation JSONB NOT NULL DEFAULT '{}'::jsonb, source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), deployment_status TEXT NOT NULL DEFAULT 'NOT_DEPLOYED', UNIQUE(tenant_id, name, version)
);
ALTER TABLE runtime_modules ADD COLUMN IF NOT EXISTS deployment_status TEXT NOT NULL DEFAULT 'NOT_DEPLOYED';
CREATE TABLE IF NOT EXISTS audit_events (
  id BIGSERIAL PRIMARY KEY, tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL, workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_uol_events_tenant_time ON uol_events(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_modules_tenant_state ON runtime_modules(tenant_id, state);
CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_time ON audit_events(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_semantic_memory_tenant ON semantic_memory(tenant_id);

-- v0.7: capability plans and execution records; status marks successful runs for duplicate protection.
CREATE TABLE IF NOT EXISTS saas_plans (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  objective TEXT NOT NULL,
  services JSONB NOT NULL DEFAULT '[]'::jsonb,
  plan JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'PLANNED' CHECK (status IN ('PLANNED','APPROVED','IN_PROGRESS','COMPLETED','BLOCKED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS saas_plan_executions (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL REFERENCES saas_plans(id) ON DELETE CASCADE,
  action_index INTEGER NOT NULL,
  result JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'RECORDED',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_saas_plans_workspace_time ON saas_plans(tenant_id,workspace_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_saas_plan_executions_plan ON saas_plan_executions(tenant_id,workspace_id,plan_id,created_at);
