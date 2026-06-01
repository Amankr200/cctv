"""
Ingest events from JSONL file into the running API.
Usage: python pipeline/ingest_events.py [events.jsonl] [api_url]
"""
import json
import sys
import time

import requests

EVENTS_FILE = sys.argv[1] if len(sys.argv) > 1 else "data/events.jsonl"
API_URL = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
BATCH_SIZE = 100


def main():
    print(f"Loading events from {EVENTS_FILE}...")
    with open(EVENTS_FILE, "r") as f:
        events = [json.loads(line) for line in f if line.strip()]

    print(f"Loaded {len(events)} events. Ingesting into {API_URL}...")

    total_accepted = 0
    total_rejected = 0
    start = time.time()

    for i in range(0, len(events), BATCH_SIZE):
        batch = events[i:i + BATCH_SIZE]
        try:
            resp = requests.post(
                f"{API_URL}/events/ingest",
                json={"events": batch},
                timeout=30,
            )
            result = resp.json()
            accepted = result.get("accepted", 0)
            rejected = result.get("rejected", 0)
            total_accepted += accepted
            total_rejected += rejected
            print(f"  Batch {i // BATCH_SIZE + 1}: {accepted} accepted, {rejected} rejected")

            if rejected > 0:
                for err in result.get("errors", [])[:3]:
                    print(f"    Error: {err}")
        except Exception as e:
            print(f"  Batch {i // BATCH_SIZE + 1}: ERROR - {e}")
            total_rejected += len(batch)

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Accepted: {total_accepted}")
    print(f"  Rejected: {total_rejected}")

    # Verify
    try:
        health = requests.get(f"{API_URL}/health").json()
        print(f"\nAPI Health: {health['status']}")
        for store in health.get("stores", []):
            print(f"  {store['store_id']}: {store['event_count']} events, last={store.get('last_event_timestamp')}")
    except Exception as e:
        print(f"Could not check health: {e}")


if __name__ == "__main__":
    main()
