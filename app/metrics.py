"""
Metrics endpoint — GET /stores/{store_id}/metrics
Real-time computation of store analytics with POS correlation for conversion rate.
"""
import logging
import json
from datetime import datetime, timedelta
from fastapi import APIRouter

from .models import StoreMetrics, QueueStats
from . import database as db

logger = logging.getLogger("store_intelligence.metrics")
router = APIRouter()


@router.get("/stores/{store_id}/metrics", response_model=StoreMetrics)
async def get_store_metrics(store_id: str):
    """
    Returns today's real-time metrics:
    - Unique visitors (non-staff ENTRY events)
    - Conversion rate (visitors in billing zone within 5-min window before POS transaction)
    - Avg dwell per zone
    - Current queue depth
    - Abandonment rate
    """
    # Unique visitors
    unique_visitors = await db.get_unique_visitors(store_id)

    # POS transactions
    transactions = await db.get_pos_transactions(store_id)
    total_transactions = len(transactions)
    total_revenue = sum(t["basket_value_inr"] for t in transactions)

    # Conversion rate: visitors who were in billing zone within 5-min window before a POS transaction
    conversion_rate = 0.0
    if unique_visitors > 0 and total_transactions > 0:
        # Get all billing zone events
        billing_events = await db.get_events_by_store(store_id, event_type="ZONE_ENTER")
        billing_visitors = set()
        for evt in billing_events:
            if evt.get("zone_id") == "BILLING":
                billing_visitors.add(evt["visitor_id"])

        # Get visitors who were in billing zone near a POS transaction
        converted_visitors = set()
        for txn in transactions:
            txn_ts = datetime.fromisoformat(txn["timestamp"].replace("Z", "+00:00"))
            window_start = txn_ts - timedelta(minutes=5)

            for evt in billing_events:
                if evt.get("zone_id") != "BILLING":
                    continue
                evt_ts = datetime.fromisoformat(evt["timestamp"].replace("Z", "+00:00"))
                if window_start <= evt_ts <= txn_ts:
                    converted_visitors.add(evt["visitor_id"])

        if unique_visitors > 0:
            conversion_rate = len(converted_visitors) / unique_visitors
        conversion_rate = min(conversion_rate, 1.0)

    # Avg dwell per zone
    dwell_stats = await db.get_zone_dwell_stats(store_id)
    avg_dwell_by_zone = {zone: stats["avg_dwell_ms"] for zone, stats in dwell_stats.items()}

    # Queue stats
    queue_stats = await db.get_billing_queue_stats(store_id)

    return StoreMetrics(
        store_id=store_id,
        timestamp=datetime.utcnow().isoformat() + "Z",
        unique_visitors=unique_visitors,
        conversion_rate=round(conversion_rate, 4),
        avg_dwell_by_zone=avg_dwell_by_zone,
        queue_stats=QueueStats(
            current_queue_depth=queue_stats["current_queue_depth"],
            abandonment_rate=round(queue_stats["abandonment_rate"], 4),
            join_count=queue_stats["join_count"],
            abandon_count=queue_stats["abandon_count"],
        ),
        total_transactions=total_transactions,
        total_revenue=round(total_revenue, 2),
    )
