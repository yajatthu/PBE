from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class DeploymentState(str, Enum):
    GENERATING="GENERATING"; COMPILED="COMPILED"; TESTING="TESTING"; STAGED="STAGED"; ACTIVE="ACTIVE"; DEGRADED="DEGRADED"; DEPRECATED="DEPRECATED"
class SourceVector(str, Enum):
    gmail_webhook="gmail_webhook"; plaid_sync="plaid_sync"; stripe_webhook="stripe_webhook"; demo="demo"
class UOLEvent(BaseModel):
    event_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_vector: SourceVector
    entity_context: Dict[str, Any]
    payload_hash: str
    anonymized_telemetry: str
class PMInput(BaseModel):
    tenant_id: str
    rolling_log_context: List[UOLEvent]
    active_database_schema_graph: Dict[str, Any]
class PMOutput(BaseModel):
    action_required: bool
    architectural_reasoning: str
    target_specification_document: Dict[str, Any]
class EngineerInput(BaseModel):
    tenant_id: str
    specification_document: Dict[str, Any]
    current_active_codebase_references: List[str] = Field(default_factory=list)
class GeneratedModule(BaseModel):
    module_id: str
    version: int
    name: str
    purpose: str
    state: DeploymentState
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    backend_python_router_code: str
    frontend_json_layout_schema: Dict[str, Any]
    security_permission_manifest: Dict[str, Any]
    generated_module_hash: str
    validation: Dict[str, Any] = Field(default_factory=dict)
    source_event_ids: List[str] = Field(default_factory=list)
    reasoning: str = ""
    deployment_status: str = "NOT_DEPLOYED"
class DemoEventRequest(BaseModel):
    tenant_id: str = Field(default="demo_furniture_co", max_length=120)
    event_type: str = Field(default="customer_request", min_length=1, max_length=80)
    customer: str = Field(default="Customer A", max_length=200)
    message: str = Field(default="We need a recurring maintenance subscription for our installed furniture portfolio.", min_length=1, max_length=4000)
