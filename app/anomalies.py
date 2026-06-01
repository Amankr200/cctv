"""
Anomaly detection endpoint — GET /stores/{store_id}/anomalies
Detects queue spikes, conversion drops, and dead zones.
"""
import logging
import json
from datetime import datetime, timedelta
from fastapi import APIRouter

from .models import AnomalyResponse, Anomaly, AnomalySeverity
from . import database as db

logger = logging.getLogger("store_intelligence.anomalies")
router = APIRouter()


@router.get("/stores/{store_id}/anomalies", response_model=AnomalyResponse)
async def get_store_anomalies(store_id: str):
    """
    Active anomalies with severity and suggested actions:
    - BILLING_QUEUE_SPIKE: queue depth > 2x average
    - CONVERSION_DROP: conversion rate significantly below historical
    - DEAD_ZONE: no visits in 30+ minutes
    """
    anomalies = []
    now = datetime.utcnow()

    # 1. Queue spike detection
    queue_stats = await db.get_billing_queue_stats(store_id)
    if queue_stats["current_queue_depth"] > 0:
        # Compare against average
        events = await db.get_events_by_store(store_id, event_type="BILLING_QUEUE_JOIN")
        if events:
            depths = []
            for evt in events:
                meta = json.loads(evt.get("metadata_json", "{}"))
                d = meta.get("queue_depth", 0)
                if d and d > 0:
                    depths.append(d)

            avg_depth = sum(depths) / len(depths) if depths else 1
            current = queue_stats["current_queue_depth"]

            if current > 2 * avg_depth and current >= 3:
                anomalies.append(Anomaly(
                    store_id=store_id,
                    anomaly_type="BILLING_QUEUE_SPIKE",
                    severity=AnomalySeverity.CRITICAL if current > 3 * avg_depth else AnomalySeverity.WARN,
                    description=f"Queue depth is {current}, which is {current/avg_depth:.1f}x the average of {avg_depth:.1f}",
                    suggested_action="Open additional billing counter or deploy staff to assist queue management",
                    detected_at=now.isoformat() + "Z",
                    metadata={"current_depth": current, "avg_depth": round(avg_depth, 1)},
                ))

    # 2. Conversion drop
    unique_visitors = await db.get_unique_visitors(store_id)
    transactions = await db.get_pos_transactions(store_id)

    if unique_visitors > 5:  # Need minimum sample
        # Simple conversion: transactions / visitors
        raw_conversion = len(transactions) / unique_visitors if unique_visitors > 0 else 0

        # Baseline expectation for retail: ~20-30% is normal
        # If significantly below, flag it
        if raw_conversion < 0.10 and unique_visitors >= 10:
            anomalies.append(Anomaly(
                store_id=store_id,
                anomaly_type="CONVERSION_DROP",
                severity=AnomalySeverity.WARN if raw_conversion > 0.05 else AnomalySeverity.CRITICAL,
                description=f"Conversion rate is {raw_conversion*100:.1f}%, significantly below expected baseline",
                suggested_action="Review product placement, check pricing, or deploy sales staff to high-traffic zones",
                detected_at=now.isoformat() + "Z",
                metadata={"conversion_rate": round(raw_conversion, 4), "visitors": unique_visitors, "transactions": len(transactions)},
            ))

    # 3. Dead zone detection — zones with no visits in 30+ minutes
    zone_visits = await db.get_zone_visit_counts(store_id)
    all_events = await db.get_events_by_store(store_id)

    if all_events:
        # Get last event time per zone
        zone_last_seen = {}
        for evt in all_events:
            zone = evt.get("zone_id")
            if zone and evt["event_type"] in ("ZONE_ENTER", "ZONE_DWELL"):
                ts = evt["timestamp"]
                if zone not in zone_last_seen or ts > zone_last_seen[zone]:
                    zone_last_seen[zone] = ts

        # Check for dead zones (no activity in 30+ minutes)
        latest_event_ts = max(evt["timestamp"] for evt in all_events)
        try:
            latest_dt = datetime.fromisoformat(latest_event_ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            latest_dt = now

        expected_zones = {"SKINCARE", "MAKEUP", "FOH", "BILLING", "ACCESSORIES"}
        for zone_id in expected_zones:
            if zone_id in zone_last_seen:
                try:
                    last_seen = datetime.fromisoformat(zone_last_seen[zone_id].replace("Z", "+00:00"))
                    gap_minutes = (latest_dt - last_seen).total_seconds() / 60
                    if gap_minutes > 30:
                        anomalies.append(Anomaly(
                            store_id=store_id,
                            anomaly_type="DEAD_ZONE",
                            severity=AnomalySeverity.INFO if gap_minutes < 60 else AnomalySeverity.WARN,
                            description=f"Zone {zone_id} has had no visitor activity for {gap_minutes:.0f} minutes",
                            suggested_action=f"Check if zone {zone_id} displays are properly lit and stocked. Consider repositioning promotional material.",
                            detected_at=now.isoformat() + "Z",
                            metadata={"zone_id": zone_id, "gap_minutes": round(gap_minutes, 1)},
                        ))
                except Exception:
                    pass
            elif zone_id in zone_visits:
                pass  # Has visits but no recent data
            else:
                # Zone never visited — could be a data issue or genuinely dead
                anomalies.append(Anomaly(
                    store_id=store_id,
                    anomaly_type="DEAD_ZONE",
                    severity=AnomalySeverity.INFO,
                    description=f"Zone {zone_id} has had zero recorded visits",
                    suggested_action=f"Verify camera coverage for zone {zone_id}. If coverage is confirmed, review zone positioning and signage.",
                    detected_at=now.isoformat() + "Z",
                    metadata={"zone_id": zone_id, "gap_minutes": None},
                ))

    # 4. High abandonment rate
    if queue_stats["join_count"] >= 3 and queue_stats["abandonment_rate"] > 0.3:
        anomalies.append(Anomaly(
            store_id=store_id,
            anomaly_type="HIGH_ABANDONMENT",
            severity=AnomalySeverity.WARN if queue_stats["abandonment_rate"] < 0.5 else AnomalySeverity.CRITICAL,
            description=f"Billing queue abandonment rate is {queue_stats['abandonment_rate']*100:.1f}%",
            suggested_action="Speed up checkout process. Consider adding express counter for small baskets.",
            detected_at=now.isoformat() + "Z",
            metadata={
                "abandonment_rate": round(queue_stats["abandonment_rate"], 4),
                "join_count": queue_stats["join_count"],
                "abandon_count": queue_stats["abandon_count"],
            },
        ))

    return AnomalyResponse(store_id=store_id, anomalies=anomalies)
