"""
Staff detector — Classifies detected persons as staff or customer.
Uses behavioral heuristics and appearance features.
"""
import numpy as np
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


class StaffDetector:
    """
    Staff detection using behavioral and appearance heuristics.

    Staff characteristics observed in the footage:
    1. Staff wear dark/black uniforms (seen in CAM 1 and CAM 2)
    2. Staff remain in the store throughout the entire clip
    3. Staff move between zones frequently (serving customers)
    4. Staff tend to stay behind counters (billing, fragrance)
    5. Staff in CAM 4 (backroom) are definitely staff

    Detection approach:
    - Tracks presence duration: persons visible for >80% of clip are likely staff
    - Color histogram: dark clothing (black uniform) detection
    - Position patterns: persons staying behind counters
    - Camera 4 (backroom): everyone is staff
    """

    def __init__(self, total_frames: int, fps: float = 30.0):
        self.total_frames = total_frames
        self.fps = fps
        self.track_history: Dict[int, List[dict]] = defaultdict(list)  # track_id -> [{frame, bbox, color_hist}]
        self.staff_scores: Dict[int, float] = {}
        self._dark_clothing_threshold = 0.4  # Fraction of dark pixels to classify as dark clothing

    def update(self, track_id: int, frame_num: int, bbox: tuple, frame_crop: Optional[np.ndarray] = None,
               camera_id: str = ""):
        """
        Update track with new detection.

        Args:
            track_id: Unique track identifier
            frame_num: Current frame number
            bbox: (x1, y1, x2, y2) bounding box
            frame_crop: Cropped image of the person (optional, for color analysis)
            camera_id: Camera identifier
        """
        entry = {
            "frame": frame_num,
            "bbox": bbox,
            "camera_id": camera_id,
            "is_dark_clothing": False,
        }

        # Color analysis for uniform detection
        if frame_crop is not None and frame_crop.size > 0:
            try:
                entry["is_dark_clothing"] = self._analyze_clothing_color(frame_crop)
            except Exception:
                pass

        self.track_history[track_id].append(entry)

    def _analyze_clothing_color(self, crop: np.ndarray) -> bool:
        """
        Analyze if the person is wearing dark clothing (staff uniform).
        Focuses on the torso region (middle 40-80% of height).
        """
        if crop is None or crop.size == 0:
            return False

        h, w = crop.shape[:2]
        if h < 10 or w < 5:
            return False

        # Focus on torso region (40-80% height)
        torso = crop[int(h * 0.3):int(h * 0.7), :]

        if torso.size == 0:
            return False

        # Convert to grayscale
        if len(torso.shape) == 3:
            gray = np.mean(torso, axis=2)
        else:
            gray = torso

        # Dark pixels: intensity < 80 (out of 255)
        dark_fraction = np.mean(gray < 80)
        return dark_fraction > self._dark_clothing_threshold

    def classify(self, track_id: int, camera_id: str = "") -> Tuple[bool, float]:
        """
        Classify whether a track is staff or customer.

        Returns:
            (is_staff: bool, confidence: float)
        """
        if track_id not in self.track_history:
            return False, 0.5

        history = self.track_history[track_id]
        if not history:
            return False, 0.5

        score = 0.0
        reasons = []

        # 1. Camera 4 (backroom) → always staff
        if camera_id == "CAM_BACKROOM_04":
            return True, 0.95

        # 2. Presence duration: staff visible for >70% of clip
        frame_range = history[-1]["frame"] - history[0]["frame"] + 1
        presence_ratio = len(history) / max(self.total_frames, 1)
        if presence_ratio > 0.7:
            score += 0.4
            reasons.append("long_presence")
        elif presence_ratio > 0.5:
            score += 0.2
            reasons.append("medium_presence")

        # 3. Dark clothing (uniform detection)
        dark_count = sum(1 for e in history if e.get("is_dark_clothing", False))
        dark_ratio = dark_count / len(history) if history else 0
        if dark_ratio > 0.6:
            score += 0.3
            reasons.append("dark_clothing")

        # 4. Position behind counter (billing area — low y in CAM 5)
        if camera_id == "CAM_BILLING_05":
            behind_counter = sum(
                1 for e in history
                if e["bbox"][1] < 400  # top portion = behind counter
            )
            if behind_counter / len(history) > 0.7:
                score += 0.3
                reasons.append("behind_counter")

        # 5. Multi-zone movement (staff serve customers across zones)
        # This is harder to detect from single-camera tracks

        is_staff = score >= 0.5
        confidence = min(0.5 + score, 0.99)

        self.staff_scores[track_id] = score
        return is_staff, confidence

    def get_staff_tracks(self, camera_id: str = "") -> set:
        """Get all track IDs classified as staff."""
        staff = set()
        for track_id in self.track_history:
            is_staff, _ = self.classify(track_id, camera_id)
            if is_staff:
                staff.add(track_id)
        return staff
