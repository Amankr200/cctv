"""
Event ingestion endpoint — POST /events/ingest
Idempotent by event_id, supports batch up to 500, partial success on malformed events.
"""
import logging
import json
from fastapi import APIRouter, Request
from pydantic import ValidationError

from .models import StoreEvent, IngestRequest, IngestResponse, EventMetadata
from . import database as db

logger = logging.getLogger("store_intelligence.ingestion")
router = APIRouter()


@router.post("/events/ingest", response_model=IngestResponse)
async def ingest_events(request: Request):
    """
    Ingest a batch of up to 500 events.
    Idempotent by event_id — safe to call twice with same payload.
    Returns partial success for malformed events.
    """
    body = await request.json()

    # Handle both {events: [...]} and direct [...]
    if isinstance(body, list):
        raw_events = body
    elif isinstance(body, dict) and "events" in body:
        raw_events = body["events"]
    else:
        return IngestResponse(accepted=0, rejected=1, errors=[{"error": "Invalid request body. Expected {events: [...]} or [...]"}])

    if len(raw_events) > 500:
        return IngestResponse(
            accepted=0,
            rejected=len(raw_events),
            errors=[{"error": f"Batch size {len(raw_events)} exceeds maximum of 500"}]
        )

    accepted = 0
    rejected = 0
    errors = []
    
    # Simple in-memory map for cross-camera deduplication
    if not hasattr(router, "vid_map"):
        router.vid_map = {}
        router.recent_exits = []  # List of (timestamp_sec, camera_id, visitor_id)

    import time
    now_sec = time.time()
    # Clean up old exits (older than 15 seconds)
    router.recent_exits = [e for e in router.recent_exits if now_sec - e[0] < 15]

    for i, raw_event in enumerate(raw_events):
        try:
            vid = raw_event.get("visitor_id")
            camera_id = raw_event.get("camera_id")
            event_type = raw_event.get("event_type")
            
            # Apply known mappings
            if vid in router.vid_map:
                raw_event["visitor_id"] = router.vid_map[vid]
                
            # Cross-camera deduplication logic
            if event_type in ["ENTRY", "ZONE_ENTER"] and vid not in router.vid_map:
                for exit_time, exit_cam, exit_vid in router.recent_exits:
                    if exit_cam != camera_id:
                        # Match found: someone exited a different camera recently
                        router.vid_map[vid] = exit_vid
                        raw_event["visitor_id"] = exit_vid
                        router.recent_exits.remove((exit_time, exit_cam, exit_vid))
                        break
                        
            if event_type in ["EXIT", "ZONE_EXIT"]:
                router.recent_exits.append((now_sec, camera_id, raw_event.get("visitor_id")))

            # Validate with Pydantic
            event = StoreEvent(**raw_event)
            event_dict = event.model_dump()

            # Convert metadata to serializable format
            if isinstance(event_dict.get("metadata"), dict):
                pass  # already dict from model_dump
            elif hasattr(event_dict.get("metadata"), "model_dump"):
                event_dict["metadata"] = event_dict["metadata"].model_dump()

            inserted = await db.insert_event(event_dict)
            accepted += 1

        except ValidationError as e:
            rejected += 1
            errors.append({
                "index": i,
                "event_id": raw_event.get("event_id", "unknown"),
                "error": str(e),
            })
        except Exception as e:
            rejected += 1
            errors.append({
                "index": i,
                "event_id": raw_event.get("event_id", "unknown"),
                "error": f"Unexpected error: {str(e)}",
            })

    logger.info(f"Ingested batch: {accepted} accepted, {rejected} rejected")
    return IngestResponse(accepted=accepted, rejected=rejected, errors=errors)
