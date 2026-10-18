import asyncio, json, logging
from celery_app import celery_app
from pbe.db import db
from pbe.core.engine import PBEEngine
from pbe.core.schemas import UOLEvent, SourceVector

log=logging.getLogger(__name__)

@celery_app.task(name="pbe.process_uol_event", bind=True, max_retries=3, default_retry_delay=5)
def process_uol_event(self, event_id: str):
    try:
        with db() as conn:
            row=conn.execute("UPDATE uol_events SET processing_status='PROCESSING', processing_error=NULL WHERE event_id=%s AND processing_status='PENDING' RETURNING tenant_id,workspace_id,timestamp,source_vector,entity_context,payload_hash,anonymized_telemetry",(event_id,)).fetchone()
            if not row:
                status=conn.execute("SELECT processing_status FROM uol_events WHERE event_id=%s",(event_id,)).fetchone()
                return {"status":status[0] if status else "missing_or_already_claimed","event_id":event_id}
        tenant_id,workspace_id,timestamp,source,entity,payload_hash,telemetry=row
        if source not in {x.value for x in SourceVector}:
            source=SourceVector.demo.value
        event=UOLEvent(event_id=event_id,timestamp=timestamp,source_vector=source,entity_context=entity,payload_hash=payload_hash,anonymized_telemetry=telemetry)
        engine=PBEEngine(str(tenant_id),str(workspace_id) if workspace_id else None)
        engine.events.append(event)
        result=asyncio.run(engine.evolve(str(tenant_id),str(workspace_id) if workspace_id else None))
        with db() as conn:
            conn.execute("UPDATE uol_events SET processing_status='PROCESSED', processed_at=now(), processing_error=NULL WHERE event_id=%s",(event_id,))
        return {"status":"processed","event_id":event_id,"module_id":result.module_id if result else None}
    except Exception as exc:
        try:
            next_status = "PENDING" if getattr(self.request, "retries", 0) < self.max_retries else "FAILED"
            with db() as conn: conn.execute("UPDATE uol_events SET processing_status=%s, processing_error=%s WHERE event_id=%s",(next_status,type(exc).__name__,event_id))
        except Exception: log.exception("Could not record UOL processing failure")
        log.exception("UOL processing failed for event %s",event_id)
        raise self.retry(exc=exc)
