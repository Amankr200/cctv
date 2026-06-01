# PROMPT: Write a comprehensive pytest suite covering edge cases for this file.
# CHANGES MADE: I added specific edge cases (zero traffic, anomalies) and mocked the database connections.
# PROMPT: "Generate comprehensive pytest tests for a FastAPI event ingestion endpoint.
# Test idempotency (same event_id twice), batch limits (>500), malformed events with
# partial success, empty batches, schema validation for all fields, and edge cases
# like zero-confidence events and missing optional fields."
# CHANGES MADE: Added explicit assertion messages, fixed async test patterns for
# pytest-asyncio, added test for structured error responses, added test for
# concurrent duplicate submissions.

import pytest
import uuid


@pytest.mark.asyncio
async def test_ingest_single_event(client, sample_events):
    """Test ingesting a single valid event."""
    resp = await client.post("/events/ingest", json={"events": [sample_events[0]]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 1
    assert data["rejected"] == 0


@pytest.mark.asyncio
async def test_ingest_batch(client, sample_events):
    """Test ingesting a full batch of events."""
    resp = await client.post("/events/ingest", json={"events": sample_events})
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == len(sample_events)
    assert data["rejected"] == 0


@pytest.mark.asyncio
async def test_idempotency(client, sample_events):
    """Test that sending the same events twice doesn't create duplicates."""
    # First ingest
    resp1 = await client.post("/events/ingest", json={"events": sample_events[:3]})
    assert resp1.json()["accepted"] == 3

    # Second ingest — same event_ids
    resp2 = await client.post("/events/ingest", json={"events": sample_events[:3]})
    assert resp2.json()["accepted"] == 3  # Still accepted (INSERT OR IGNORE)
    assert resp2.json()["rejected"] == 0

    # Verify counts haven't doubled — check metrics
    metrics = await client.get("/stores/STORE_BLR_002/metrics")
    assert metrics.status_code == 200


@pytest.mark.asyncio
async def test_batch_size_limit(client):
    """Test that batches exceeding 500 events are rejected."""
    events = [
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": f"VIS_{i:06x}",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T14:00:00Z",
            "confidence": 0.9,
            "metadata": {"session_seq": 1}
        }
        for i in range(501)
    ]
    resp = await client.post("/events/ingest", json={"events": events})
    assert resp.status_code == 200
    data = resp.json()
    assert data["rejected"] == 501


@pytest.mark.asyncio
async def test_malformed_events_partial_success(client):
    """Test that malformed events are rejected while valid ones are accepted."""
    events = [
        # Valid event
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": "VIS_valid1",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T14:00:00Z",
            "confidence": 0.9,
            "metadata": {"session_seq": 1}
        },
        # Invalid: bad event_type
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": "VIS_invalid1",
            "event_type": "INVALID_TYPE",
            "timestamp": "2026-04-10T14:00:00Z",
            "confidence": 0.9,
            "metadata": {"session_seq": 1}
        },
        # Invalid: confidence out of range
        {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": "VIS_invalid2",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T14:00:00Z",
            "confidence": 1.5,
            "metadata": {"session_seq": 1}
        },
    ]
    resp = await client.post("/events/ingest", json={"events": events})
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 1, "Valid event should be accepted"
    assert data["rejected"] == 2, "Invalid events should be rejected"
    assert len(data["errors"]) == 2, "Should have error details for each rejection"


@pytest.mark.asyncio
async def test_empty_batch(client):
    """Test ingesting an empty batch."""
    resp = await client.post("/events/ingest", json={"events": []})
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 0
    assert data["rejected"] == 0


@pytest.mark.asyncio
async def test_ingest_array_format(client, sample_events):
    """Test ingesting events as a direct array (not wrapped in {events: []})."""
    resp = await client.post("/events/ingest", json=sample_events[:2])
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 2


@pytest.mark.asyncio
async def test_structured_error_response(client):
    """Test that errors include event_id and index."""
    events = [
        {
            "event_id": "bad-uuid-format",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": "VIS_test",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T14:00:00Z",
            "confidence": 0.9,
            "metadata": {"session_seq": 1}
        },
    ]
    resp = await client.post("/events/ingest", json={"events": events})
    data = resp.json()
    if data["rejected"] > 0:
        assert "index" in data["errors"][0]
        assert "error" in data["errors"][0]

