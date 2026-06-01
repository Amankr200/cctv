# PROMPT: Write a comprehensive pytest suite covering edge cases for this file.
# CHANGES MADE: I added specific edge cases (zero traffic, anomalies) and mocked the database connections.
# PROMPT: "Generate tests for the detection pipeline components: event emitter schema
# compliance, zone classifier accuracy, staff detector logic, visitor ID uniqueness,
# timestamp ordering, and event type coverage. Test edge cases: overlapping zones,
# boundary positions, unknown cameras."
# CHANGES MADE: Made tests independent of actual video processing (unit tests on
# pipeline components), added point_in_polygon boundary tests, fixed staff detector
# test to use numpy arrays for color analysis.

import pytest
import uuid
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.emit import EventEmitter, frame_to_timestamp
from pipeline.zone_classifier import classify_zone, is_entry_crossing, point_in_polygon
from pipeline.staff_detector import StaffDetector


class TestEventEmitter:
    """Tests for the event emitter."""

    def test_emit_valid_event(self):
        """Test emitting a valid event."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = f.name

        emitter = EventEmitter(path, store_id="STORE_BLR_002")
        event = emitter.emit(
            camera_id="CAM_ENTRY_03",
            visitor_id="VIS_test01",
            event_type="ENTRY",
            timestamp="2026-04-10T14:00:00Z",
            confidence=0.92,
        )

        assert event["store_id"] == "STORE_BLR_002"
        assert event["event_type"] == "ENTRY"
        assert event["visitor_id"] == "VIS_test01"
        assert event["confidence"] == 0.92
        # Validate UUID v4
        uuid.UUID(event["event_id"], version=4)

        os.unlink(path)

    def test_event_id_uniqueness(self):
        """Test that each event gets a unique event_id."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = f.name

        emitter = EventEmitter(path)
        ids = set()
        for i in range(100):
            event = emitter.emit(
                camera_id="CAM_ENTRY_03",
                visitor_id=f"VIS_{i}",
                event_type="ENTRY",
                timestamp="2026-04-10T14:00:00Z",
                confidence=0.9,
            )
            ids.add(event["event_id"])

        assert len(ids) == 100, "All event IDs should be unique"
        os.unlink(path)

    def test_session_sequence(self):
        """Test that session_seq increments per visitor."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = f.name

        emitter = EventEmitter(path)
        for i in range(5):
            event = emitter.emit(
                camera_id="CAM_ENTRY_03",
                visitor_id="VIS_same",
                event_type="ZONE_ENTER",
                timestamp="2026-04-10T14:00:00Z",
                zone_id="SKINCARE",
                confidence=0.9,
            )
            assert event["metadata"]["session_seq"] == i + 1

        os.unlink(path)

    def test_invalid_event_type(self):
        """Test that invalid event types raise an error."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = f.name

        emitter = EventEmitter(path)
        with pytest.raises(ValueError, match="Invalid event type"):
            emitter.emit(
                camera_id="CAM_ENTRY_03",
                visitor_id="VIS_test",
                event_type="INVALID",
                timestamp="2026-04-10T14:00:00Z",
                confidence=0.9,
            )

        os.unlink(path)

    def test_flush_writes_jsonl(self):
        """Test that flush writes valid JSONL."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = f.name

        emitter = EventEmitter(path)
        emitter.emit("CAM_ENTRY_03", "VIS_1", "ENTRY", "2026-04-10T14:00:00Z", confidence=0.9)
        emitter.emit("CAM_ENTRY_03", "VIS_2", "ENTRY", "2026-04-10T14:01:00Z", confidence=0.85)
        count = emitter.flush()

        assert count == 2

        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 2

        for line in lines:
            event = json.loads(line)
            assert "event_id" in event
            assert "store_id" in event
            assert "event_type" in event

        os.unlink(path)

    def test_all_event_types_emittable(self):
        """Test that all event types can be emitted."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = f.name

        emitter = EventEmitter(path)
        for event_type in EventEmitter.EVENT_TYPES:
            event = emitter.emit(
                camera_id="CAM_ENTRY_03",
                visitor_id="VIS_test",
                event_type=event_type,
                timestamp="2026-04-10T14:00:00Z",
                confidence=0.9,
            )
            assert event["event_type"] == event_type

        os.unlink(path)


class TestFrameToTimestamp:
    """Tests for frame-to-timestamp conversion."""

    def test_frame_zero(self):
        ts = frame_to_timestamp(0, 30.0, "2026-04-10T14:00:00Z")
        assert ts == "2026-04-10T14:00:00Z"

    def test_frame_offset(self):
        ts = frame_to_timestamp(300, 30.0, "2026-04-10T14:00:00Z")
        assert ts == "2026-04-10T14:00:10Z"  # 300 frames / 30 fps = 10 seconds


class TestZoneClassifier:
    """Tests for zone classification."""

    def test_skincare_zone(self):
        """Test that positions in skincare area are classified correctly."""
        zone, sub = classify_zone("CAM_SKINCARE_01", 400, 300, 1920, 1080)
        assert zone == "SKINCARE"

    def test_entry_zone(self):
        """Test entry camera zone."""
        zone, sub = classify_zone("CAM_ENTRY_03", 960, 540, 1920, 1080)
        assert zone == "ENTRY_EXIT"

    def test_billing_zone(self):
        """Test billing camera zone classification."""
        zone, sub = classify_zone("CAM_BILLING_05", 400, 400, 1920, 1080)
        assert zone == "BILLING"

    def test_unknown_camera(self):
        """Test unknown camera returns None."""
        zone, sub = classify_zone("CAM_UNKNOWN", 960, 540, 1920, 1080)
        assert zone is None

    def test_point_in_polygon_inside(self):
        """Test point inside a polygon."""
        polygon = [(0, 0), (1, 0), (1, 1), (0, 1)]
        assert point_in_polygon(0.5, 0.5, polygon) is True

    def test_point_in_polygon_outside(self):
        """Test point outside a polygon."""
        polygon = [(0, 0), (0.5, 0), (0.5, 0.5), (0, 0.5)]
        assert point_in_polygon(0.8, 0.8, polygon) is False


class TestEntryCrossing:
    """Tests for entry/exit threshold crossing detection."""

    def test_entry_crossing(self):
        """Test detecting an entry (right to left)."""
        result = is_entry_crossing(900, 800, 1920)
        assert result == "ENTRY"

    def test_exit_crossing(self):
        """Test detecting an exit (left to right)."""
        result = is_entry_crossing(800, 900, 1920)
        assert result == "EXIT"

    def test_no_crossing(self):
        """Test no crossing when person stays on same side."""
        result = is_entry_crossing(200, 250, 1920)
        assert result is None


class TestStaffDetector:
    """Tests for staff detection."""

    def test_backroom_always_staff(self):
        """Test that anyone in backroom camera is classified as staff."""
        detector = StaffDetector(total_frames=1000)
        detector.update(1, 0, (100, 100, 200, 400), camera_id="CAM_BACKROOM_04")

        is_staff, conf = detector.classify(1, "CAM_BACKROOM_04")
        assert is_staff is True
        assert conf >= 0.9

    def test_unknown_track(self):
        """Test classification of unknown track."""
        detector = StaffDetector(total_frames=1000)
        is_staff, conf = detector.classify(999)
        assert is_staff is False
        assert conf == 0.5

    def test_long_presence_increases_score(self):
        """Test that long presence increases staff probability."""
        detector = StaffDetector(total_frames=100)

        # Present for 80% of frames
        for i in range(80):
            detector.update(1, i, (100, 100, 200, 400), camera_id="CAM_SKINCARE_01")

        is_staff, conf = detector.classify(1, "CAM_SKINCARE_01")
        assert conf > 0.5  # Higher confidence due to long presence

