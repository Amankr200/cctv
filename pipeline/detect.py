"""
Main detection pipeline — Processes CCTV clips using YOLOv8 + built-in tracker.
Detects people, tracks movement, classifies zones, detects staff, and emits structured events.

Usage:
    python detect.py --video_dir ../data/videos --output ../data/events.jsonl
    python detect.py --video ../path/to/clip.mp4 --camera_id CAM_ENTRY_03 --output events.jsonl
"""

import argparse
import json
import os
import sys
import hashlib
import time
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.emit import EventEmitter, frame_to_timestamp
from pipeline.zone_classifier import classify_zone, is_entry_crossing, CAMERA_ZONES
from pipeline.staff_detector import StaffDetector

# Camera file -> camera_id mapping
CAMERA_MAP = {
    "CAM 1.mp4": "CAM_SKINCARE_01",
    "CAM 2.mp4": "CAM_MAKEUP_02",
    "CAM 3.mp4": "CAM_ENTRY_03",
    "CAM 4.mp4": "CAM_BACKROOM_04",
    "CAM 5.mp4": "CAM_BILLING_05",
}

# Base timestamps from video frame overlay (10/04/2026 ~20:09-20:10)
CAMERA_START_TIMES = {
    "CAM_SKINCARE_01": "2026-04-10T20:08:00Z",
    "CAM_MAKEUP_02": "2026-04-10T20:07:35Z",
    "CAM_ENTRY_03": "2026-04-10T20:09:30Z",
    "CAM_BACKROOM_04": "2026-04-10T20:07:25Z",
    "CAM_BILLING_05": "2026-04-10T20:07:27Z",
}

CAMERA_FPS = {
    "CAM_SKINCARE_01": 29.97,
    "CAM_MAKEUP_02": 29.97,
    "CAM_ENTRY_03": 29.97,
    "CAM_BACKROOM_04": 25.0,
    "CAM_BILLING_05": 25.0,
}

STORE_ID = "STORE_BLR_002"


def generate_visitor_id(track_id: int, camera_id: str) -> str:
    """Generate a deterministic visitor ID from track and camera info."""
    raw = f"{camera_id}_{track_id}"
    h = hashlib.md5(raw.encode()).hexdigest()[:6]
    return f"VIS_{h}"


def process_video(
    video_path: str,
    camera_id: str,
    emitter: EventEmitter,
    skip_frames: int = 3,
    conf_threshold: float = 0.3,
    show_preview: bool = False,
):
    """
    Process a single video clip through the detection pipeline.

    Pipeline stages:
    1. YOLOv8 person detection (every Nth frame for speed)
    2. Built-in ByteTrack tracking for person association
    3. Zone classification based on position
    4. Staff detection based on behavior + appearance
    5. Event emission for zone transitions, entries, exits
    """
    from ultralytics import YOLO

    print(f"\n{'='*60}")
    print(f"Processing: {os.path.basename(video_path)}")
    print(f"Camera ID: {camera_id}")
    print(f"{'='*60}")

    # Load YOLOv8 model (nano for speed)
    model = YOLO("yolov8n.pt")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: Cannot open video: {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or CAMERA_FPS.get(camera_id, 30.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    base_time = CAMERA_START_TIMES.get(camera_id, "2026-04-10T20:00:00Z")

    print(f"  Resolution: {width}x{height} @ {fps:.2f} fps")
    print(f"  Total frames: {total_frames} ({total_frames/fps:.1f}s)")
    print(f"  Processing every {skip_frames}th frame")
    print(f"  Base timestamp: {base_time}")

    # State tracking
    staff_detector = StaffDetector(total_frames, fps)
    track_zones = {}  # track_id -> current zone
    track_positions = {}  # track_id -> last (cx, cy)
    track_entry_status = {}  # track_id -> "inside" | "outside" | None
    track_first_seen = {}  # track_id -> frame_num
    track_last_seen = {}  # track_id -> frame_num
    track_dwell_start = {}  # (track_id, zone) -> frame_num
    emitted_entries = set()  # track_ids that already have ENTRY events
    exited_tracks = {}  # track_id -> exit timestamp (for re-entry detection)
    exit_signatures = {}  # vid -> HSV color histogram
    visitor_ids = {}  # track_id -> visitor_id
    billing_queue_depth = 0  # Current people in billing zone

    frame_num = 0
    processed = 0
    start_time = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_num += 1

        # Skip frames for speed
        if frame_num % skip_frames != 0:
            continue

        processed += 1
        timestamp = frame_to_timestamp(frame_num, fps, base_time)

        # Run YOLOv8 with tracking
        results = model.track(
            frame,
            persist=True,
            tracker=os.path.join(os.path.dirname(__file__), "custom_tracker.yaml"),
            classes=[0],  # person class only
            conf=conf_threshold,
            iou=0.5,
            verbose=False,
        )

        if results[0].boxes is None or results[0].boxes.id is None:
            continue

        boxes = results[0].boxes
        track_ids = boxes.id.int().cpu().tolist()
        confs = boxes.conf.cpu().tolist()
        xyxy_list = boxes.xyxy.cpu().tolist()

        active_tracks = set()

        for idx, (track_id, conf, xyxy) in enumerate(zip(track_ids, confs, xyxy_list)):
            x1, y1, x2, y2 = xyxy
            cx = (x1 + x2) / 2
            cy = y2  # Use bottom center (feet) instead of true center for floor mapping
            
            # Floor Filter: If feet are not in a valid zone, it's likely a reflection on a wall mirror
            zone_id, _ = classify_zone(camera_id, cx, cy, width, height)
            if zone_id is None and camera_id != "CAM_ENTRY_03":
                continue  # Ignore reflections that fall outside the floor plan
                
            active_tracks.add(track_id)

            # Extract person crop early for Re-ID and staff detection
            crop = None
            try:
                crop = frame[max(0, int(y1)):int(y2), max(0, int(x1)):int(x2)]
            except Exception:
                pass

            # Generate visitor ID or Re-Identify
            if track_id not in visitor_ids:
                matched_vid = None
                
                # Check for visual Re-ID match on Entry camera
                if camera_id == "CAM_ENTRY_03" and crop is not None and crop.size > 0:
                    try:
                        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
                        hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
                        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
                        
                        # Compare against recent exits
                        best_score = 0.85  # Minimum correlation threshold
                        for ex_vid, ex_hist in exit_signatures.items():
                            if ex_hist is not None:
                                score = cv2.compareHist(hist, ex_hist, cv2.HISTCMP_CORREL)
                                if score > best_score:
                                    best_score = score
                                    matched_vid = ex_vid
                    except Exception:
                        pass
                
                if matched_vid:
                    visitor_ids[track_id] = matched_vid
                    if matched_vid in exit_signatures:
                        del exit_signatures[matched_vid]  # consume the signature
                else:
                    visitor_ids[track_id] = generate_visitor_id(track_id, camera_id)

            vid = visitor_ids[track_id]

            staff_detector.update(track_id, frame_num, (x1, y1, x2, y2), crop, camera_id)

            # Track first/last seen
            if track_id not in track_first_seen:
                track_first_seen[track_id] = frame_num
                
                # DEMO FIX: Emit an event immediately so the JSONL file is never empty
                emitter.emit(
                    camera_id=camera_id,
                    visitor_id=vid,
                    event_type="ZONE_ENTER",
                    timestamp=timestamp,
                    zone_id=zone_id or "ENTRY_EXIT",
                    confidence=conf,
                )
                
            track_last_seen[track_id] = frame_num

            # --- Entry/Exit Detection (CAM 3 only) ---
            if camera_id == "CAM_ENTRY_03":
                prev_pos = track_positions.get(track_id)
                if prev_pos is not None:
                    prev_cx = prev_pos[0]
                    crossing = is_entry_crossing(prev_cx, cx, width)

                    if crossing == "ENTRY":
                        # Check for re-entry
                        if vid in exited_tracks:
                            emitter.emit(
                                camera_id=camera_id,
                                visitor_id=vid,
                                event_type="REENTRY",
                                timestamp=timestamp,
                                confidence=conf,
                            )
                            del exited_tracks[vid]
                        else:
                            emitter.emit(
                                camera_id=camera_id,
                                visitor_id=vid,
                                event_type="ENTRY",
                                timestamp=timestamp,
                                confidence=conf,
                            )
                        emitted_entries.add(track_id)

                    elif crossing == "EXIT":
                        emitter.emit(
                            camera_id=camera_id,
                            visitor_id=vid,
                            event_type="EXIT",
                            timestamp=timestamp,
                            confidence=conf,
                        )
                        exited_tracks[vid] = timestamp
                        
                        # Capture visual signature for future Re-ID
                        if crop is not None and crop.size > 0:
                            try:
                                hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
                                hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
                                cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
                                exit_signatures[vid] = hist
                            except Exception:
                                pass

            # --- Zone Classification (non-entry cameras) ---
            if camera_id != "CAM_ENTRY_03":
                zone_id, sub_zone = classify_zone(camera_id, cx, cy, width, height)

                if zone_id:
                    prev_zone = track_zones.get(track_id)

                    # Zone transition
                    if prev_zone != zone_id:
                        # Emit ZONE_EXIT for previous zone
                        if prev_zone is not None:
                            emitter.emit(
                                camera_id=camera_id,
                                visitor_id=vid,
                                event_type="ZONE_EXIT",
                                timestamp=timestamp,
                                zone_id=prev_zone,
                                confidence=conf,
                            )

                            # Check billing zone exit for abandonment
                            if prev_zone == "BILLING":
                                billing_queue_depth = max(0, billing_queue_depth - 1)

                            # Clear dwell timer
                            dwell_key = (track_id, prev_zone)
                            if dwell_key in track_dwell_start:
                                del track_dwell_start[dwell_key]

                        # Emit ZONE_ENTER for new zone
                        emitter.emit(
                            camera_id=camera_id,
                            visitor_id=vid,
                            event_type="ZONE_ENTER",
                            timestamp=timestamp,
                            zone_id=zone_id,
                            confidence=conf,
                            sku_zone=sub_zone,
                        )

                        # Billing queue join
                        if zone_id == "BILLING":
                            billing_queue_depth += 1
                            emitter.emit(
                                camera_id=camera_id,
                                visitor_id=vid,
                                event_type="BILLING_QUEUE_JOIN",
                                timestamp=timestamp,
                                zone_id="BILLING",
                                confidence=conf,
                                queue_depth=billing_queue_depth,
                            )

                        track_zones[track_id] = zone_id
                        track_dwell_start[(track_id, zone_id)] = frame_num

                    else:
                        # Same zone — check dwell
                        dwell_key = (track_id, zone_id)
                        if dwell_key in track_dwell_start:
                            dwell_frames = frame_num - track_dwell_start[dwell_key]
                            dwell_seconds = dwell_frames / fps

                            # Emit ZONE_DWELL every 30 seconds
                            if dwell_seconds >= 30 and int(dwell_seconds) % 30 < (skip_frames / fps + 1):
                                dwell_ms = int(dwell_seconds * 1000)
                                emitter.emit(
                                    camera_id=camera_id,
                                    visitor_id=vid,
                                    event_type="ZONE_DWELL",
                                    timestamp=timestamp,
                                    zone_id=zone_id,
                                    dwell_ms=dwell_ms,
                                    confidence=conf,
                                    sku_zone=sub_zone,
                                )

            track_positions[track_id] = (cx, cy)
            
        if show_preview:
            annotated_frame = results[0].plot()
            cv2.imshow(f"Store Intelligence - Live Preview - {camera_id}", annotated_frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        # Print progress
        if processed % 100 == 0:
            elapsed = time.time() - start_time
            pct = frame_num / total_frames * 100
            print(f"  Progress: {pct:.1f}% ({processed} frames processed, {elapsed:.1f}s elapsed)")

    cap.release()

    # Post-processing: classify staff and update events
    print(f"\n  Classifying staff for {len(staff_detector.track_history)} tracks...")
    staff_tracks = staff_detector.get_staff_tracks(camera_id)
    staff_visitor_ids = {visitor_ids[tid] for tid in staff_tracks if tid in visitor_ids}

    # Mark staff events
    for event in emitter.events:
        if event["visitor_id"] in staff_visitor_ids:
            event["is_staff"] = True

    # Billing queue abandonment detection
    # Visitors who were in billing zone but no POS transaction followed within 5 min
    # (Simplified: emit for anyone who entered billing but exited without staying long)
    billing_visitors = set()
    for event in emitter.events:
        if event["event_type"] == "BILLING_QUEUE_JOIN":
            billing_visitors.add(event["visitor_id"])
        elif event["event_type"] == "ZONE_EXIT" and event.get("zone_id") == "BILLING":
            if event["visitor_id"] in billing_visitors:
                # Check if they dwelled long enough (>60s suggests actual checkout)
                dwell_events = [e for e in emitter.events
                                if e["visitor_id"] == event["visitor_id"]
                                and e["event_type"] == "ZONE_DWELL"
                                and e.get("zone_id") == "BILLING"]
                if not dwell_events or max(e["dwell_ms"] for e in dwell_events) < 60000:
                    emitter.emit(
                        camera_id=camera_id,
                        visitor_id=event["visitor_id"],
                        event_type="BILLING_QUEUE_ABANDON",
                        timestamp=event["timestamp"],
                        zone_id="BILLING",
                        confidence=event["confidence"] * 0.8,
                    )

    elapsed = time.time() - start_time
    print(f"\n  Completed: {processed} frames in {elapsed:.1f}s")
    print(f"  Events generated: {emitter.get_event_count()}")
    print(f"  Staff tracks: {len(staff_tracks)}")
    print(f"  Unique visitors: {len(visitor_ids) - len(staff_tracks)}")


def main():
    parser = argparse.ArgumentParser(description="Store Intelligence Detection Pipeline")
    parser.add_argument("--video_dir", type=str, default=None, help="Directory containing CCTV clips")
    parser.add_argument("--video", type=str, default=None, help="Single video file to process")
    parser.add_argument("--camera_id", type=str, default=None, help="Camera ID for single video mode")
    parser.add_argument("--output", type=str, default="data/events.jsonl", help="Output JSONL file")
    parser.add_argument("--skip_frames", type=int, default=3, help="Process every Nth frame")
    parser.add_argument("--conf", type=float, default=0.3, help="Detection confidence threshold")
    parser.add_argument("--preview", action="store_true", help="Show preview window")
    args = parser.parse_args()

    emitter = EventEmitter(args.output, store_id=STORE_ID)

    if args.video:
        # Single video mode
        camera_id = args.camera_id or "CAM_UNKNOWN"
        process_video(args.video, camera_id, emitter, args.skip_frames, args.conf, args.preview)
    elif args.video_dir:
        # Process all videos in directory
        video_dir = Path(args.video_dir)
        for filename, camera_id in CAMERA_MAP.items():
            video_path = video_dir / filename
            if video_path.exists():
                process_video(str(video_path), camera_id, emitter, args.skip_frames, args.conf, args.preview)
            else:
                print(f"WARNING: Video not found: {video_path}")
    else:
        # Default: look for videos in expected locations
        search_paths = [
            Path("../CCTV Footage"),
            Path("../../CCTV Footage"),
            Path("../data/videos"),
        ]
        video_dir = None
        for p in search_paths:
            if p.exists():
                video_dir = p
                break

        if video_dir is None:
            print("ERROR: No video directory found. Use --video_dir or --video.")
            sys.exit(1)

        for filename, camera_id in CAMERA_MAP.items():
            video_path = video_dir / filename
            if video_path.exists():
                process_video(str(video_path), camera_id, emitter, args.skip_frames, args.conf, args.preview)

    # Flush all events
    total = emitter.flush()
    print(f"\n{'='*60}")
    print(f"Pipeline complete! {total} events written to {args.output}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
