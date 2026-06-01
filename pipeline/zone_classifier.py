"""
Zone classifier — Maps detected person positions to store zones.
Uses camera-specific polygon regions derived from the floor plan and camera frames.
"""
from typing import Optional, Tuple


# Camera zone polygon definitions (normalized coordinates 0-1)
# Derived from manual analysis of camera frames against floor plan

CAMERA_ZONES = {
    "CAM_SKINCARE_01": {
        # CAM 1: Looking at top wall (skincare). Products on left side, F.O.H center-right
        "SKINCARE": {
            "polygon": [(0.0, 0.0), (0.85, 0.0), (0.85, 0.7), (0.0, 0.7)],
            "sub_zones": {
                "EB_KOREAN": [(0.0, 0.0), (0.12, 0.0), (0.12, 0.7), (0.0, 0.7)],
                "FACE_SHOP": [(0.12, 0.0), (0.35, 0.0), (0.35, 0.7), (0.12, 0.7)],
                "GOOD_VIBES": [(0.35, 0.0), (0.50, 0.0), (0.50, 0.7), (0.35, 0.7)],
                "DERMDOC": [(0.50, 0.0), (0.60, 0.0), (0.60, 0.7), (0.50, 0.7)],
                "MINIMALIST": [(0.60, 0.0), (0.75, 0.0), (0.75, 0.7), (0.60, 0.7)],
                "AQUALOGICA": [(0.75, 0.0), (0.85, 0.0), (0.85, 0.7), (0.75, 0.7)],
            },
        },
        "FOH": {
            "polygon": [(0.45, 0.7), (1.0, 0.7), (1.0, 1.0), (0.45, 1.0)],
        },
    },
    "CAM_MAKEUP_02": {
        # CAM 2: Looking at bottom wall (makeup brands). Accessories+Alps left, Makeup center-right
        "MAKEUP": {
            "polygon": [(0.15, 0.0), (1.0, 0.0), (1.0, 0.85), (0.15, 0.85)],
            "sub_zones": {
                "ALPS_GOODNESS": [(0.15, 0.0), (0.35, 0.0), (0.35, 0.5), (0.15, 0.5)],
                "SWISS_BEAUTY": [(0.35, 0.0), (0.50, 0.0), (0.50, 0.85), (0.35, 0.85)],
                "LAKME_MAKEUP": [(0.50, 0.0), (0.65, 0.0), (0.65, 0.85), (0.50, 0.85)],
                "FACES_CANADA": [(0.65, 0.0), (0.85, 0.0), (0.85, 0.85), (0.65, 0.85)],
                "MAYBELLINE": [(0.85, 0.0), (1.0, 0.0), (1.0, 0.85), (0.85, 0.85)],
            },
        },
        "FRAGRANCE": {
            "polygon": [(0.0, 0.2), (0.15, 0.2), (0.15, 0.6), (0.0, 0.6)],
        },
        "FOH": {
            "polygon": [(0.2, 0.85), (0.7, 0.85), (0.7, 1.0), (0.2, 1.0)],
        },
    },
    "CAM_ENTRY_03": {
        # CAM 3: Entry/Exit glass door
        "ENTRY_EXIT": {
            "polygon": [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        },
    },
    "CAM_BACKROOM_04": {
        # CAM 4: Back room - staff only
        "BACKROOM": {
            "polygon": [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        },
    },
    "CAM_BILLING_05": {
        # CAM 5: Cash counter + accessories
        "BILLING": {
            "polygon": [(0.0, 0.0), (0.55, 0.0), (0.55, 1.0), (0.0, 1.0)],
        },
        "ACCESSORIES": {
            "polygon": [(0.55, 0.0), (1.0, 0.0), (1.0, 0.7), (0.55, 0.7)],
        },
    },
}

# Entry line config for CAM 3
ENTRY_CONFIG = {
    "camera_id": "CAM_ENTRY_03",
    # The entry threshold is roughly where the glass door meets the floor
    # People moving from right (outside) to left (inside) = ENTRY
    # People moving from left (inside) to right (outside) = EXIT
    "line_x": 0.45,  # Normalized x-coordinate of the threshold line
    "direction": "horizontal",  # crossing direction check
    "inbound_direction": "right_to_left",  # outside to inside
}


def point_in_polygon(x: float, y: float, polygon: list[tuple]) -> bool:
    """
    Ray casting algorithm for point-in-polygon test.
    Polygon is a list of (x, y) tuples in normalized coordinates.
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def classify_zone(
    camera_id: str,
    bbox_center_x: float,
    bbox_center_y: float,
    frame_width: int = 1920,
    frame_height: int = 1080,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Classify which zone a person is in based on their position in the frame.

    Returns:
        (zone_id, sub_zone_id) or (None, None) if not in any zone
    """
    # Normalize coordinates
    nx = bbox_center_x / frame_width
    ny = bbox_center_y / frame_height

    zones = CAMERA_ZONES.get(camera_id, {})

    for zone_id, zone_def in zones.items():
        polygon = zone_def["polygon"]
        if point_in_polygon(nx, ny, polygon):
            # Check sub-zones
            sub_zone_id = None
            for sub_id, sub_poly in zone_def.get("sub_zones", {}).items():
                if point_in_polygon(nx, ny, sub_poly):
                    sub_zone_id = sub_id
                    break
            return zone_id, sub_zone_id

    return None, None


def is_entry_crossing(
    prev_x: float,
    curr_x: float,
    frame_width: int = 1920,
) -> Optional[str]:
    """
    Check if a person crossed the entry threshold line in CAM 3.

    Returns:
        "ENTRY" if crossing inbound (right to left / outside to inside)
        "EXIT" if crossing outbound (left to right / inside to outside)
        None if no crossing
    """
    line_x = ENTRY_CONFIG["line_x"] * frame_width

    # Check if the person crossed the line between previous and current frame
    if prev_x > line_x and curr_x <= line_x:
        return "ENTRY"  # right to left = entering store
    elif prev_x < line_x and curr_x >= line_x:
        return "EXIT"  # left to right = leaving store

    return None
