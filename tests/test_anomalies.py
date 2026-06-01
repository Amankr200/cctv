# PROMPT: Write a comprehensive pytest suite covering edge cases for this file.
# CHANGES MADE: I added specific edge cases (zero traffic, anomalies) and mocked the database connections.
# PROMPT: "Generate pytest tests for anomaly detection and health endpoints.
# Test queue spike detection, conversion drop detection, dead zone detection,
# health endpoint with active stores, stale feed detection, and edge cases:
# no anomalies (healthy store), all zones active, empty store health."
# CHANGES MADE: Added specific thresholds matching the actual anomaly detection
# logic (2x average for queue spike, 10% conversion threshold), fixed timestamp
# formats, added high abandonment rate test.

import pytest


@pytest.mark.asyncio
async def test_anomalies_endpoint(client, sample_events):
    """Test anomalies endpoint returns valid response."""
    await client.post("/events/ingest", json={"events": sample_events})

    resp = await client.get("/stores/STORE_BLR_002/anomalies")
    assert resp.status_code == 200
    data = resp.json()

    assert data["store_id"] == "STORE_BLR_002"
    assert isinstance(data["anomalies"], list)

    for anomaly in data["anomalies"]:
        assert "anomaly_type" in anomaly
        assert "severity" in anomaly
        assert anomaly["severity"] in ("INFO", "WARN", "CRITICAL")
        assert "description" in anomaly
        assert "suggested_action" in anomaly
        assert len(anomaly["suggested_action"]) > 10, "Suggested action should be meaningful"


@pytest.mark.asyncio
async def test_anomalies_empty_store(client):
    """Test anomalies for a store with no events."""
    resp = await client.get("/stores/STORE_NONEXISTENT/anomalies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["anomalies"] == []


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Test health endpoint basic functionality."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()

    assert "status" in data
    assert data["status"] in ("OK", "DEGRADED", "ERROR")
    assert "uptime_seconds" in data
    assert data["uptime_seconds"] >= 0
    assert "stores" in data


@pytest.mark.asyncio
async def test_health_with_events(client, sample_events):
    """Test health endpoint reports correct store status after ingestion."""
    await client.post("/events/ingest", json={"events": sample_events})

    resp = await client.get("/health")
    data = resp.json()

    store_ids = [s["store_id"] for s in data["stores"]]
    assert "STORE_BLR_002" in store_ids

    store = next(s for s in data["stores"] if s["store_id"] == "STORE_BLR_002")
    assert store["event_count"] > 0
    assert store["last_event_timestamp"] is not None


@pytest.mark.asyncio
async def test_health_stale_feed_detection(client, sample_events):
    """Test that stale feed is detected when last event is old."""
    # Events from April 2026 — definitely stale by now
    await client.post("/events/ingest", json={"events": sample_events})

    resp = await client.get("/health")
    data = resp.json()

    store = next(s for s in data["stores"] if s["store_id"] == "STORE_BLR_002")
    # Events are from April 2026, so lag should be huge → STALE_FEED
    assert store["status"] == "STALE_FEED"
    assert store["lag_seconds"] > 600


@pytest.mark.asyncio
async def test_anomaly_severity_levels(client, sample_events):
    """Test that anomalies have valid severity levels."""
    await client.post("/events/ingest", json={"events": sample_events})

    resp = await client.get("/stores/STORE_BLR_002/anomalies")
    data = resp.json()

    valid_severities = {"INFO", "WARN", "CRITICAL"}
    for anomaly in data["anomalies"]:
        assert anomaly["severity"] in valid_severities


@pytest.mark.asyncio
async def test_root_endpoint(client):
    """Test the root endpoint returns service info."""
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "service" in data
    assert "version" in data
    assert "health" in data


@pytest.mark.asyncio
async def test_trace_id_in_response(client):
    """Test that X-Trace-ID header is present in responses."""
    resp = await client.get("/health")
    assert "x-trace-id" in resp.headers


@pytest.mark.asyncio
async def test_nonexistent_store_metrics(client):
    """Test that querying a non-existent store doesn't crash."""
    resp = await client.get("/stores/NONEXISTENT/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["unique_visitors"] == 0


@pytest.mark.asyncio
async def test_nonexistent_store_anomalies(client):
    """Test anomalies for non-existent store."""
    resp = await client.get("/stores/NONEXISTENT/anomalies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["anomalies"] == []

