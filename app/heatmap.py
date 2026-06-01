"""
Heatmap endpoint — GET /stores/{store_id}/heatmap
Zone visit frequency + avg dwell, normalized 0-100.
"""
import logging
from fastapi import APIRouter

from .models import HeatmapResponse, HeatmapZone
from . import database as db

logger = logging.getLogger("store_intelligence.heatmap")
router = APIRouter()

ZONE_NAMES = {
    "SKINCARE": "Skincare Zone",
    "MAKEUP": "Makeup Zone",
    "FOH": "Front of House",
    "FRAGRANCE": "Fragrance Zone",
    "NAIL_UNIT": "Nail Unit",
    "BILLING": "Billing / Cash Counter",
    "ACCESSORIES": "Accessories",
    "ALPS_GOODNESS": "Alps Goodness / Streax",
    "PMU": "Permanent Makeup Unit",
    "ENTRY_EXIT": "Entry / Exit",
    "BACKROOM": "Back Room",
    "EB_KOREAN": "EB Korean",
    "FACE_SHOP": "The Face Shop",
    "GOOD_VIBES": "Good Vibes",
    "DERMDOC": "DermDoc",
    "MINIMALIST": "Minimalist",
    "AQUALOGICA": "Aqualogica",
    "LAKME_SKIN": "Lakme Skin",
    "MAYBELLINE": "Maybelline",
    "FACES_CANADA": "Faces Canada",
    "LAKME_MAKEUP": "Lakme Makeup",
    "COLORBAR_SUGAR": "Colorbar + Sugar",
    "SWISS_BEAUTY": "Swiss Beauty",
    "RENEE_NYBAE": "Renee / NY Bae",
}


@router.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
async def get_store_heatmap(store_id: str):
    """
    Zone visit frequency and average dwell time, normalized 0-100.
    Includes data_confidence flag if fewer than 20 sessions in window.
    """
    zone_visits = await db.get_zone_visit_counts(store_id)
    dwell_stats = await db.get_zone_dwell_stats(store_id)

    # Merge data
    all_zones = set(list(zone_visits.keys()) + list(dwell_stats.keys()))

    zones_data = []
    max_visits = max((zone_visits.get(z, {}).get("unique_visitors", 0) for z in all_zones), default=1) or 1

    for zone_id in sorted(all_zones):
        visit_info = zone_visits.get(zone_id, {"unique_visitors": 0, "total_events": 0})
        dwell_info = dwell_stats.get(zone_id, {"avg_dwell_ms": 0, "count": 0})

        visit_count = visit_info["unique_visitors"]
        avg_dwell = dwell_info["avg_dwell_ms"]

        # Normalize: combine visit frequency and dwell time
        # 70% weight on visits, 30% on dwell
        visit_score = (visit_count / max_visits) * 100 if max_visits > 0 else 0

        max_dwell = max((dwell_stats.get(z, {}).get("avg_dwell_ms", 0) for z in all_zones), default=1) or 1
        dwell_score = (avg_dwell / max_dwell) * 100 if max_dwell > 0 else 0

        normalized = round(0.7 * visit_score + 0.3 * dwell_score, 1)
        normalized = min(normalized, 100.0)

        zones_data.append(HeatmapZone(
            zone_id=zone_id,
            zone_name=ZONE_NAMES.get(zone_id, zone_id),
            visit_count=visit_count,
            avg_dwell_ms=round(avg_dwell, 2),
            normalized_score=normalized,
            data_confidence=visit_count >= 20,
        ))

    # Sort by normalized score descending
    zones_data.sort(key=lambda z: z.normalized_score, reverse=True)

    return HeatmapResponse(store_id=store_id, zones=zones_data)
