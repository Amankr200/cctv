# PROMPT: "Generate pytest fixtures and conftest for a FastAPI application that uses
# aiosqlite. Need an async test client, temporary database, and sample event data
# covering all event types in the schema. Include edge cases: empty store,
# all-staff events, zero purchases, re-entry scenarios."
# CHANGES MADE: Added POS transaction fixtures, customised event data to match
# actual store layout zones, added billing queue events with queue_depth metadata,
# fixed async teardown to properly clean temp files.

import os
import sys
import json
import asyncio
import tempfile
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def app():
    """Create a fresh FastAPI app with temporary database."""
    # Use temp database
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DB_PATH"] = tmp.name
    os.environ["POS_CSV_PATH"] = ""

    from app.main import app as fastapi_app
    from app.database import init_db, close_db

    await init_db()
    yield fastapi_app
    await close_db()

    # Cleanup
    try:
        os.unlink(tmp.name)
    except Exception:
        pass


@pytest_asyncio.fixture
async def client(app):
    """Async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_events():
    """Complete set of sample events covering all event types."""
    return [
        {
            "event_id": "00000000-0000-4000-8000-000000000001",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": "VIS_abc123",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T14:00:00Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.92,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000002",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_SKINCARE_01",
            "visitor_id": "VIS_abc123",
            "event_type": "ZONE_ENTER",
            "timestamp": "2026-04-10T14:00:30Z",
            "zone_id": "SKINCARE",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.88,
            "metadata": {"queue_depth": None, "sku_zone": "GOOD_VIBES", "session_seq": 2}
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000003",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_SKINCARE_01",
            "visitor_id": "VIS_abc123",
            "event_type": "ZONE_DWELL",
            "timestamp": "2026-04-10T14:01:00Z",
            "zone_id": "SKINCARE",
            "dwell_ms": 30000,
            "is_staff": False,
            "confidence": 0.88,
            "metadata": {"queue_depth": None, "sku_zone": "GOOD_VIBES", "session_seq": 3}
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000004",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_SKINCARE_01",
            "visitor_id": "VIS_abc123",
            "event_type": "ZONE_EXIT",
            "timestamp": "2026-04-10T14:02:00Z",
            "zone_id": "SKINCARE",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.85,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 4}
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000005",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_BILLING_05",
            "visitor_id": "VIS_abc123",
            "event_type": "ZONE_ENTER",
            "timestamp": "2026-04-10T14:03:00Z",
            "zone_id": "BILLING",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.90,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 5}
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000006",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_BILLING_05",
            "visitor_id": "VIS_abc123",
            "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": "2026-04-10T14:03:05Z",
            "zone_id": "BILLING",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.90,
            "metadata": {"queue_depth": 2, "sku_zone": None, "session_seq": 6}
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000007",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": "VIS_abc123",
            "event_type": "EXIT",
            "timestamp": "2026-04-10T14:10:00Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.91,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 7}
        },
        # Second visitor — staff member
        {
            "event_id": "00000000-0000-4000-8000-000000000008",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_MAKEUP_02",
            "visitor_id": "VIS_staff01",
            "event_type": "ZONE_ENTER",
            "timestamp": "2026-04-10T14:00:00Z",
            "zone_id": "MAKEUP",
            "dwell_ms": 0,
            "is_staff": True,
            "confidence": 0.95,
            "metadata": {"queue_depth": None, "sku_zone": "FACES_CANADA", "session_seq": 1}
        },
        # Third visitor — enters and re-enters
        {
            "event_id": "00000000-0000-4000-8000-000000000009",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": "VIS_def456",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T14:15:00Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.87,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000010",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": "VIS_def456",
            "event_type": "EXIT",
            "timestamp": "2026-04-10T14:20:00Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.86,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 2}
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000011",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": "VIS_def456",
            "event_type": "REENTRY",
            "timestamp": "2026-04-10T14:25:00Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.82,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 3}
        },
        # Fourth visitor — billing queue abandon
        {
            "event_id": "00000000-0000-4000-8000-000000000012",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_03",
            "visitor_id": "VIS_ghi789",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T14:30:00Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.93,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}
        },
        {
            "event_id": "00000000-0000-4000-8000-00000000012a",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_SKINCARE_01",
            "visitor_id": "VIS_ghi789",
            "event_type": "ZONE_ENTER",
            "timestamp": "2026-04-10T14:32:00Z",
            "zone_id": "SKINCARE",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.90,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 2}
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000013",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_BILLING_05",
            "visitor_id": "VIS_ghi789",
            "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": "2026-04-10T14:35:00Z",
            "zone_id": "BILLING",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.88,
            "metadata": {"queue_depth": 3, "sku_zone": None, "session_seq": 3}
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000014",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_BILLING_05",
            "visitor_id": "VIS_ghi789",
            "event_type": "BILLING_QUEUE_ABANDON",
            "timestamp": "2026-04-10T14:38:00Z",
            "zone_id": "BILLING",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.75,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 4}
        },
    ]


@pytest.fixture
def sample_pos_transactions():
    """Sample POS transactions for conversion rate testing."""
    return [
        {
            "transaction_id": "TXN_001",
            "store_id": "STORE_BLR_002",
            "timestamp": "2026-04-10T14:05:00Z",
            "basket_value_inr": 1240.00
        },
        {
            "transaction_id": "TXN_002",
            "store_id": "STORE_BLR_002",
            "timestamp": "2026-04-10T14:42:00Z",
            "basket_value_inr": 680.00
        },
    ]


@pytest.fixture
def empty_store_events():
    """Events for an empty store scenario."""
    return []


@pytest.fixture
def all_staff_events():
    """Events where all detected persons are staff."""
    return [
        {
            "event_id": "00000000-0000-4000-8000-000000000020",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_MAKEUP_02",
            "visitor_id": "VIS_staff_a",
            "event_type": "ZONE_ENTER",
            "timestamp": "2026-04-10T10:00:00Z",
            "zone_id": "MAKEUP",
            "dwell_ms": 0,
            "is_staff": True,
            "confidence": 0.95,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}
        },
        {
            "event_id": "00000000-0000-4000-8000-000000000021",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_BILLING_05",
            "visitor_id": "VIS_staff_b",
            "event_type": "ZONE_ENTER",
            "timestamp": "2026-04-10T10:00:00Z",
            "zone_id": "BILLING",
            "dwell_ms": 0,
            "is_staff": True,
            "confidence": 0.93,
            "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1}
        },
    ]
