"""
Seed data for the Store Intelligence API.
Generates realistic sample events so the dashboard shows meaningful metrics
when deployed to a fresh environment (e.g., Render, Docker).
"""
import uuid
import random
from datetime import datetime, timedelta

STORE_ID = "STORE_BLR_002"
ZONES = ["SKINCARE", "MAKEUP", "FRAGRANCE", "HAIR_CARE", "BATH_AND_BODY"]
BASE_TIME = datetime(2026, 4, 10, 10, 0, 0)


def generate_seed_events():
    """Generate a realistic set of ~300 events for one store day."""
    events = []
    visitor_count = 0
    session_seq_map = {}

    # Simulate 45 unique visitors over an 8-hour window
    for i in range(45):
        visitor_count += 1
        vid = f"VIS_{uuid.uuid4().hex[:8]}"
        session_seq_map[vid] = 0
        is_staff = (i < 4)  # First 4 are staff

        # Random entry time spread across the day
        entry_offset = timedelta(minutes=random.randint(0, 480))
        entry_time = BASE_TIME + entry_offset

        def next_seq():
            session_seq_map[vid] += 1
            return session_seq_map[vid]

        def make_event(event_type, ts, zone_id=None, dwell_ms=0, meta=None):
            e = {
                "event_id": str(uuid.uuid4()),
                "store_id": STORE_ID,
                "camera_id": "CAM_ENTRY_03" if event_type in ("ENTRY", "EXIT", "REENTRY") else "CAM_FLOOR_02",
                "visitor_id": vid,
                "event_type": event_type,
                "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "zone_id": zone_id,
                "dwell_ms": dwell_ms,
                "is_staff": is_staff,
                "confidence": round(random.uniform(0.75, 0.98), 2),
                "metadata": {
                    "queue_depth": None,
                    "sku_zone": zone_id,
                    "session_seq": next_seq(),
                },
            }
            if meta:
                e["metadata"].update(meta)
            return e

        # ENTRY
        events.append(make_event("ENTRY", entry_time))

        if is_staff:
            # Staff just dwell in zones for a long time then exit
            for zone in ZONES:
                t = entry_time + timedelta(minutes=random.randint(5, 60))
                events.append(make_event("ZONE_ENTER", t, zone_id=zone))
                dwell = random.randint(60000, 300000)
                events.append(make_event("ZONE_DWELL", t + timedelta(seconds=30), zone_id=zone, dwell_ms=dwell))
                events.append(make_event("ZONE_EXIT", t + timedelta(milliseconds=dwell), zone_id=zone, dwell_ms=dwell))
            exit_time = entry_time + timedelta(hours=random.randint(4, 8))
            events.append(make_event("EXIT", exit_time))
            continue

        # Regular customer journey
        # Visit 1-3 zones
        num_zones = random.randint(1, 3)
        visited_zones = random.sample(ZONES, num_zones)
        current_time = entry_time + timedelta(seconds=random.randint(10, 60))

        for zone in visited_zones:
            events.append(make_event("ZONE_ENTER", current_time, zone_id=zone))
            dwell = random.randint(15000, 120000)
            if dwell >= 30000:
                events.append(make_event("ZONE_DWELL", current_time + timedelta(seconds=30), zone_id=zone, dwell_ms=dwell))
            current_time = current_time + timedelta(milliseconds=dwell)
            events.append(make_event("ZONE_EXIT", current_time, zone_id=zone, dwell_ms=dwell))
            current_time = current_time + timedelta(seconds=random.randint(5, 30))

        # 60% of customers go to billing
        if random.random() < 0.60:
            queue_depth = random.randint(0, 5)
            events.append(make_event("BILLING_QUEUE_JOIN", current_time, zone_id="BILLING",
                                     meta={"queue_depth": queue_depth}))
            billing_dwell = random.randint(30000, 180000)
            current_time = current_time + timedelta(milliseconds=billing_dwell)

            # 20% abandon the queue
            if random.random() < 0.20:
                events.append(make_event("BILLING_QUEUE_ABANDON", current_time, zone_id="BILLING",
                                         dwell_ms=billing_dwell))
            else:
                events.append(make_event("ZONE_EXIT", current_time, zone_id="BILLING", dwell_ms=billing_dwell))

        # 10% chance of re-entry
        if random.random() < 0.10:
            reentry_time = current_time + timedelta(minutes=random.randint(5, 20))
            events.append(make_event("EXIT", current_time))
            events.append(make_event("REENTRY", reentry_time))
            current_time = reentry_time + timedelta(minutes=random.randint(2, 10))

        # EXIT
        exit_time = current_time + timedelta(seconds=random.randint(10, 60))
        events.append(make_event("EXIT", exit_time))

    # Sort by timestamp
    events.sort(key=lambda e: e["timestamp"])
    return events
