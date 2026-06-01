import asyncio
import httpx
import uuid
import random
import logging
from datetime import datetime, timedelta

API_URL = "http://127.0.0.1:8000/events/ingest"
STORE_ID = "STORE_BLR_002"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("simulator")

ZONES = ["SKINCARE", "MAKEUP", "FOH", "BILLING", "ACCESSORIES"]
CAMERAS = ["CAM_ENTRY_03", "CAM_SKINCARE_01", "CAM_BILLING_05"]

async def simulate():
    async with httpx.AsyncClient() as client:
        visitor_count = 0
        active_visitors = []

        while True:
            events = []
            now = datetime.utcnow()

            # Randomly generate new visitors
            if random.random() < 0.3:
                visitor_count += 1
                vid = f"VIS_SIM_{visitor_count:04d}"
                active_visitors.append(vid)
                events.append({
                    "event_id": str(uuid.uuid4()),
                    "store_id": STORE_ID,
                    "camera_id": "CAM_ENTRY_03",
                    "visitor_id": vid,
                    "event_type": "ENTRY",
                    "timestamp": now.isoformat() + "Z",
                    "zone_id": None,
                    "dwell_ms": 0,
                    "is_staff": False,
                    "confidence": 0.95,
                    "metadata": {"session_seq": 1}
                })

            # Randomly move active visitors
            for vid in list(active_visitors):
                if random.random() < 0.4:
                    zone = random.choice(ZONES)
                    events.append({
                        "event_id": str(uuid.uuid4()),
                        "store_id": STORE_ID,
                        "camera_id": random.choice(CAMERAS),
                        "visitor_id": vid,
                        "event_type": "ZONE_ENTER",
                        "timestamp": now.isoformat() + "Z",
                        "zone_id": zone,
                        "dwell_ms": 0,
                        "is_staff": False,
                        "confidence": 0.9,
                        "metadata": {"session_seq": random.randint(2, 5)}
                    })
                
                # Join queue
                if random.random() < 0.2:
                    events.append({
                        "event_id": str(uuid.uuid4()),
                        "store_id": STORE_ID,
                        "camera_id": "CAM_BILLING_05",
                        "visitor_id": vid,
                        "event_type": "BILLING_QUEUE_JOIN",
                        "timestamp": now.isoformat() + "Z",
                        "zone_id": "BILLING",
                        "dwell_ms": 0,
                        "is_staff": False,
                        "confidence": 0.9,
                        "metadata": {"queue_depth": random.randint(1, 6)}
                    })
                
                # Exit
                if random.random() < 0.1:
                    events.append({
                        "event_id": str(uuid.uuid4()),
                        "store_id": STORE_ID,
                        "camera_id": "CAM_ENTRY_03",
                        "visitor_id": vid,
                        "event_type": "EXIT",
                        "timestamp": now.isoformat() + "Z",
                        "zone_id": None,
                        "dwell_ms": 0,
                        "is_staff": False,
                        "confidence": 0.95,
                        "metadata": {}
                    })
                    active_visitors.remove(vid)

            if events:
                try:
                    resp = await client.post(API_URL, json={"events": events})
                    logger.info(f"Ingested {len(events)} events, Response: {resp.status_code}")
                except Exception as e:
                    logger.error(f"Failed to ingest: {e}")

            await asyncio.sleep(2.0)

if __name__ == "__main__":
    asyncio.run(simulate())
