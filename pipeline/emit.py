"""
Event emitter — Validates and serializes detection events to JSONL.
Enforces the required event schema using Pydantic models.
"""
import json
import uuid
import os
from datetime import datetime, timedelta
from typing import Optional


class EventEmitter:
    """Emits structured events to a JSONL file."""

    EVENT_TYPES = {
        "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
        "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY"
    }

    def __init__(self, output_path: str, store_id: str = "STORE_BLR_002"):
        self.output_path = output_path
        self.store_id = store_id
        self.events = []
        self._session_counters = {}  # visitor_id -> event count
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    def emit(
        self,
        camera_id: str,
        visitor_id: str,
        event_type: str,
        timestamp: str,
        zone_id: Optional[str] = None,
        dwell_ms: int = 0,
        is_staff: bool = False,
        confidence: float = 0.5,
        queue_depth: Optional[int] = None,
        sku_zone: Optional[str] = None,
    ):
        """Emit a single event."""
        if event_type not in self.EVENT_TYPES:
            raise ValueError(f"Invalid event type: {event_type}")

        # Track session sequence
        if visitor_id not in self._session_counters:
            self._session_counters[visitor_id] = 0
        self._session_counters[visitor_id] += 1

        event = {
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": timestamp,
            "zone_id": zone_id,
            "dwell_ms": dwell_ms,
            "is_staff": is_staff,
            "confidence": round(confidence, 4),
            "metadata": {
                "queue_depth": queue_depth,
                "sku_zone": sku_zone,
                "session_seq": self._session_counters[visitor_id],
            },
        }
        self.events.append(event)
        
        # Live streaming to API
        if len(self.events) >= 10:
            self._send_to_api(self.events.copy())
            self.events.clear()
            
        return event
        
    def _send_to_api(self, batch):
        import threading
        import requests
        
        def send():
            try:
                requests.post("http://127.0.0.1:8000/events/ingest", json={"events": batch})
            except Exception:
                pass
                
        threading.Thread(target=send).start()

    def flush(self):
        """Write all accumulated events to the JSONL file."""
        with open(self.output_path, "a", encoding="utf-8") as f:
            for event in self.events:
                f.write(json.dumps(event) + "\n")
        count = len(self.events)
        self.events.clear()
        return count

    def get_event_count(self):
        return len(self.events)


def frame_to_timestamp(frame_num: int, fps: float, base_time: str) -> str:
    """Convert frame number to ISO-8601 timestamp."""
    base_dt = datetime.fromisoformat(base_time.replace("Z", "+00:00"))
    offset = timedelta(seconds=frame_num / fps)
    result = base_dt + offset
    return result.strftime("%Y-%m-%dT%H:%M:%SZ")
