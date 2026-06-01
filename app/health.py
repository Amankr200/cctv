"""
Health endpoint — GET /health
Service status, last event per store, stale feed warnings.
"""
import logging
import time
from datetime import datetime, timezone
from fastapi import APIRouter

from .models import HealthResponse, StoreHealth
from . import database as db

logger = logging.getLogger("store_intelligence.health")
router = APIRouter()

_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Service health check.
    Reports status, uptime, last event per store, and STALE_FEED warnings.
    """
    uptime = time.time() - _start_time
    stores = []
    overall_status = "OK"

    try:
        store_ids = await db.get_all_store_ids()

        if not store_ids:
            # No data yet — still healthy, just empty
            return HealthResponse(
                status="OK",
                uptime_seconds=round(uptime, 2),
                stores=[],
            )

        for store_id in store_ids:
            last_ts = await db.get_last_event_timestamp(store_id)
            event_count = await db.get_event_count(store_id)

            status = "OK"
            lag_seconds = None

            if last_ts:
                try:
                    last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    lag_seconds = (now - last_dt).total_seconds()

                    if lag_seconds > 600:  # 10 minutes
                        status = "STALE_FEED"
                        overall_status = "DEGRADED"
                except (ValueError, TypeError):
                    status = "UNKNOWN"
            else:
                status = "NO_DATA"

            stores.append(StoreHealth(
                store_id=store_id,
                status=status,
                last_event_timestamp=last_ts,
                event_count=event_count,
                lag_seconds=round(lag_seconds, 2) if lag_seconds is not None else None,
            ))

    except Exception as e:
        logger.error(f"Health check error: {e}")
        overall_status = "ERROR"

    return HealthResponse(
        status=overall_status,
        uptime_seconds=round(uptime, 2),
        stores=stores,
    )
