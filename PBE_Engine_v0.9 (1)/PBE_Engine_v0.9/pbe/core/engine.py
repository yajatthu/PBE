from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from pbe.core.schemas import *
from pbe.agents.pm_agent import PMAgent
from pbe.agents.engineer_agent import EngineerAgent
from pbe.services.sandbox import validate
from pbe.services.module_registry import save_module, set_state
from pbe.services.audit import record
import logging
log = logging.getLogger(__name__)

class PBEEngine:
    def __init__(self, tenant_id=None, workspace_id=None):
        self.tenant_id=tenant_id; self.workspace_id=workspace_id; self.reset()
    def reset(self): self.events=[]; self.modules=[]; self.audit=[]; self.trace=[]; self.version_counter={}; self.demo_tenant=self.tenant_id or "demo_furniture_co"
    def _audit(self, action, detail, actor="PBE"):
        item={"timestamp":datetime.now(timezone.utc).isoformat(),"action":action,"actor":actor,"detail":detail}; self.audit.append(item); self.trace.append(item)
        if self.tenant_id:
            try: record(self.tenant_id, self.workspace_id, actor, action, {"detail": detail, "timestamp": item["timestamp"]})
            except Exception: log.exception("Failed to persist PBE audit event")
    def ingest(self, req:DemoEventRequest):
        eid="uol_"+hashlib.sha256((str(self.tenant_id or req.tenant_id)+req.event_type+req.message+str(len(self.events))+datetime.now(timezone.utc).isoformat()).encode()).hexdigest()[:32]
        ph="sha256_"+hashlib.sha256(req.message.encode()).hexdigest()
        e=UOLEvent(event_id=eid,source_vector=SourceVector.demo,entity_context={"tenant_id":req.tenant_id,"association_type":"customer_request"},payload_hash=ph,anonymized_telemetry=f"customer_request:{req.message[:160]}")
        self.events.append(e); self._audit("UOL_INGESTED",f"Observed {req.event_type}; immutable event {eid}"); return e
    async def evolve(self, tenant_id=None, workspace_id=None):
        if not self.events: return None
        self.trace=[]; self._audit("OBSERVATION_WINDOW",f"Analyzing {len(self.events)} normalized event(s)")
        pm=await PMAgent().reason(PMInput(tenant_id=tenant_id or self.demo_tenant,rolling_log_context=self.events[-10:],active_database_schema_graph={"tables":["client_subscriptions_metadata"]}))
        if not pm.action_required:
            self._audit("NO_ACTION", "Cognitive Arbiter determined no new capability is required")
            return None
        self._audit("COGNITIVE_ARBITER",pm.architectural_reasoning)
        spec=pm.target_specification_document; spec["source_event_ids"]=[e.event_id for e in self.events[-3:]]; spec["reasoning"]=pm.architectural_reasoning
        self._audit("TECHNICAL_SPEC","Defined objective, migration, API contract, UI component and approval boundary")
        key=spec.get("functional_objective","module"); self.version_counter[key]=self.version_counter.get(key,0)+1
        mod=await EngineerAgent().compile(EngineerInput(tenant_id=tenant_id or self.demo_tenant,specification_document=spec,current_active_codebase_references=[]),self.version_counter[key])
        if tenant_id and workspace_id:
            from pbe.services.module_registry import next_version
            mod.version=next_version(tenant_id, workspace_id, mod.name)
        mod.state=DeploymentState.TESTING; self._audit("COMPILE",f"Generated {mod.name} v{mod.version} with hash {mod.generated_module_hash[:16]}…")
        ok,report=validate(mod); mod.validation=report
        if ok:
            mod.state=DeploymentState.STAGED; self._audit("VALIDATION_PASSED",f"{report['passed']}/{report['total']} checks passed; module staged for owner approval")
        else:
            mod.state=DeploymentState.DEPRECATED; self._audit("VALIDATION_BLOCKED","Generated capability failed safety validation")
        self.modules.append(mod)
        if tenant_id:
            save_module(mod, tenant_id, workspace_id)
        return mod
    def approve(self,module_id, tenant_id=None, workspace_id=None):
        m=next((x for x in self.modules if x.module_id==module_id),None)
        if not m or m.state!=DeploymentState.STAGED: raise ValueError("Module is not awaiting approval")
        m.state=DeploymentState.ACTIVE; m.deployment_status="APPROVED_NOT_DEPLOYED"; self._audit("OWNER_APPROVED",f"{m.name} v{m.version} approved by workspace owner","OWNER"); self._audit("DEPLOYMENT_BOUNDARY","Approved in registry only; generated code is not hot-loaded into the live API runtime")
        if tenant_id: set_state(module_id, "ACTIVE", tenant_id, workspace_id, m.deployment_status)
        return m
    async def failure(self, tenant_id=None, workspace_id=None):
        active=next((m for m in reversed(self.modules) if m.state==DeploymentState.ACTIVE),None)
        if not active: raise ValueError("Approve a module before simulating failure")
        active.state=DeploymentState.DEGRADED; self._audit("SIMULATED_REGISTRY_FAILURE",f"Synthetic test fault recorded for {active.name} v{active.version}; no generated code was running in the live API runtime")
        active.state=DeploymentState.DEPRECATED; self._audit("SIMULATED_CIRCUIT_BREAKER","Registry state transitioned to deprecated; this is a prototype simulation, not a live runtime rollback")
        self._audit("REPAIR_QUEUE","Failure trace packaged for Compilation Engineer")
        repaired=await self.evolve(tenant_id, workspace_id)
        if repaired: self._audit("REPAIR_READY",f"Repaired version {repaired.version} staged for approval")
        return repaired
    def state(self):
        return {"events":[e.model_dump(mode="json") for e in self.events],"modules":[m.model_dump(mode="json") for m in self.modules],"audit":self.audit[-30:],"trace":self.trace[-30:],"active_count":sum(m.state==DeploymentState.ACTIVE for m in self.modules),"staged_count":sum(m.state==DeploymentState.STAGED for m in self.modules),"runtime_mode":"PODMAN COMPILE SANDBOX ENABLED" if __import__("pbe.settings",fromlist=["settings"]).settings.PBE_SANDBOX_ENABLED else "STATIC VALIDATION ONLY — GENERATED CODE NOT EXECUTED"}
