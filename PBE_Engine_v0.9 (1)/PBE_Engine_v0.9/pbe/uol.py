import hashlib, json
from datetime import datetime, timezone
from redis import Redis
from pbe.db import db
from pbe.settings import settings
from pbe.workers.tasks import process_uol_event

from pbe.privacy import redact_sensitive

def normalize_composio_event(payload: dict):
    metadata=payload.get("metadata",{}) if isinstance(payload.get("metadata",{}),dict) else {}
    data=payload.get("data",{})
    safe_data=redact_sensitive(data)
    raw=json.dumps(safe_data,sort_keys=True,separators=(",",":"),default=str)
    eid="uol_"+hashlib.sha256(str(payload.get("id",raw)).encode()).hexdigest()[:32]
    source=metadata.get("toolkit_slug") or metadata.get("trigger_slug") or "composio"
    telemetry=json.dumps({"source":source,"trigger":metadata.get("trigger_slug"),"data":safe_data},sort_keys=True,default=str)[:4000]
    stamp=payload.get("timestamp")
    try:
        if isinstance(stamp,(int,float)) or (isinstance(stamp,str) and stamp.isdigit()): stamp=datetime.fromtimestamp(float(stamp),timezone.utc).isoformat()
        elif isinstance(stamp,str): stamp=datetime.fromisoformat(stamp.replace("Z","+00:00")).astimezone(timezone.utc).isoformat()
        else: stamp=datetime.now(timezone.utc).isoformat()
    except Exception: stamp=datetime.now(timezone.utc).isoformat()
    return {"event_id":eid,"timestamp":stamp,"source_vector":source,"entity_context":{"user_id":metadata.get("user_id"),"connected_account_id":metadata.get("connected_account_id"),"trigger_id":metadata.get("trigger_id"),"association_type":"composio_event"},"payload_hash":"sha256_"+hashlib.sha256(raw.encode()).hexdigest(),"anonymized_telemetry":telemetry,"raw_metadata":redact_sensitive(metadata)}

def persist_and_queue(event: dict, tenant_id: str, workspace_id: str|None):
    with db() as conn:
        cur=conn.execute("INSERT INTO uol_events(event_id,tenant_id,workspace_id,timestamp,source_vector,entity_context,payload_hash,anonymized_telemetry,raw_metadata,processing_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING') ON CONFLICT (event_id) DO NOTHING RETURNING event_id",(event["event_id"],tenant_id,workspace_id,event["timestamp"],event["source_vector"],json.dumps(event["entity_context"]),event["payload_hash"],event["anonymized_telemetry"],json.dumps(event["raw_metadata"])))
        inserted=cur.fetchone() is not None
    if inserted:
        try:
            Redis.from_url(settings.REDIS_URL).xadd("pbe:uol", {"event_id":event["event_id"],"tenant_id":tenant_id})
        except Exception:
            # Celery is the processing queue; Redis Streams is an additional observability stream.
            pass
        process_uol_event.delay(event["event_id"])
    else:
        # If a prior delivery persisted the event but failed before enqueueing, allow safe re-enqueue.
        with db() as conn:
            row=conn.execute("SELECT processing_status FROM uol_events WHERE event_id=%s",(event["event_id"],)).fetchone()
        if row and row[0] == "PENDING": process_uol_event.delay(event["event_id"])
    return inserted
