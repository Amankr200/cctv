"""
Funnel endpoint — GET /stores/{store_id}/funnel
Session-based conversion funnel: Entry → Zone Visit → Billing Queue → Purchase
"""
import logging
import json
from datetime import datetime, timedelta
from fastapi import APIRouter

from .models import FunnelResponse, FunnelStage
from . import database as db

logger = logging.getLogger("store_intelligence.funnel")
router = APIRouter()


@router.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
async def get_store_funnel(store_id: str):
    """
    Conversion funnel with counts and drop-off percentages.
    Session is the unit — re-entries don't double-count.
    """
    sessions = await db.get_visitor_sessions(store_id)
    transactions = await db.get_pos_transactions(store_id)

    # Stage 1: Entry — unique visitors who entered
    entered_visitors = set()
    for vid, events in sessions.items():
        for evt in events:
            if evt["event_type"] in ("ENTRY", "REENTRY"):
                entered_visitors.add(vid)
                break

    # Stage 2: Zone Visit — visitors who entered at least one product zone
    zone_visitors = set()
    product_zones = {"SKINCARE", "MAKEUP", "FRAGRANCE", "ACCESSORIES", "FOH",
                     "NAIL_UNIT", "ALPS_GOODNESS", "PMU",
                     "EB_KOREAN", "FACE_SHOP", "GOOD_VIBES", "DERMDOC",
                     "MINIMALIST", "AQUALOGICA", "LAKME_SKIN",
                     "MAYBELLINE", "FACES_CANADA", "LAKME_MAKEUP",
                     "COLORBAR_SUGAR", "SWISS_BEAUTY", "RENEE_NYBAE"}
    for vid, events in sessions.items():
        if vid not in entered_visitors:
            continue
        for evt in events:
            if evt["event_type"] in ("ZONE_ENTER", "ZONE_DWELL") and evt.get("zone_id") in product_zones:
                zone_visitors.add(vid)
                break

    # Stage 3: Billing Queue — visitors who reached billing zone
    billing_visitors = set()
    for vid, events in sessions.items():
        if vid not in entered_visitors:
            continue
        for evt in events:
            if evt.get("zone_id") == "BILLING" or evt["event_type"] in ("BILLING_QUEUE_JOIN",):
                billing_visitors.add(vid)
                break

    # Stage 4: Purchase — visitors who correlate with a POS transaction
    # A visitor counts as converted if they were in billing zone within 5 min before a transaction
    purchased_visitors = set()
    billing_events = []
    for vid, events in sessions.items():
        for evt in events:
            if evt.get("zone_id") == "BILLING" or evt["event_type"] in ("BILLING_QUEUE_JOIN", "ZONE_ENTER"):
                if evt.get("zone_id") == "BILLING":
                    billing_events.append((vid, evt))

    for txn in transactions:
        txn_ts = datetime.fromisoformat(txn["timestamp"].replace("Z", "+00:00"))
        window_start = txn_ts - timedelta(minutes=5)

        for vid, evt in billing_events:
            evt_ts = datetime.fromisoformat(evt["timestamp"].replace("Z", "+00:00"))
            if window_start <= evt_ts <= txn_ts:
                purchased_visitors.add(vid)

    # Build funnel
    entry_count = len(entered_visitors)
    zone_count = len(zone_visitors)
    billing_count = len(billing_visitors)
    purchase_count = len(purchased_visitors)

    stages = [
        FunnelStage(
            stage="Entry",
            count=entry_count,
            drop_off_pct=0.0
        ),
        FunnelStage(
            stage="Zone Visit",
            count=zone_count,
            drop_off_pct=round((1 - zone_count / entry_count) * 100, 2) if entry_count > 0 else 0.0
        ),
        FunnelStage(
            stage="Billing Queue",
            count=billing_count,
            drop_off_pct=round((1 - billing_count / zone_count) * 100, 2) if zone_count > 0 else 0.0
        ),
        FunnelStage(
            stage="Purchase",
            count=purchase_count,
            drop_off_pct=round((1 - purchase_count / billing_count) * 100, 2) if billing_count > 0 else 0.0
        ),
    ]

    return FunnelResponse(store_id=store_id, stages=stages)
