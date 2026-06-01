# Architecture & Design

## System Overview
The Store Intelligence system is an end-to-end analytics pipeline designed to transform raw CCTV video streams into actionable, real-time business intelligence via a REST/WebSocket API.

The architecture is divided into two primary, decoupled subsystems:
1. **Video Analytics Pipeline** (Detection & Emission)
2. **Intelligence API** (Ingestion, Aggregation, & Delivery)

## 1. Video Analytics Pipeline (`/pipeline`)
The pipeline operates on raw video files (h264/hevc) to extract semantic spatial events without requiring heavy DB transactions on every frame.

- **Object Detection & Tracking**: Uses `ultralytics YOLOv8` coupled with `ByteTrack`. YOLOv8 provides high accuracy for person detection, while ByteTrack handles robust multi-object tracking to assign persistent IDs to individuals across frames within a single camera view.
- **Zone Classification**: Employs point-in-polygon ray-casting. The pixel coordinates of bounding box anchors (bottom center, corresponding to feet) are evaluated against normalized polygonal boundaries mapped from the `store_layout.json` (extracted from the provided Excel schematic).
- **Staff Detection**: Implemented via a heuristic-based `StaffDetector`. Rather than training a custom classifier (which requires large labeled datasets), staff are identified based on spatial persistence (e.g., spending excessive time in specific zones or backrooms) and tracking their unique trajectory over time.
- **Event Emission**: Transforms physical movements into a stream of discrete JSON Lines (`.jsonl`) events (e.g., `ENTRY`, `ZONE_ENTER`, `BILLING_QUEUE_JOIN`).

## 2. Intelligence API (`/app`)
The backend is a high-performance, asynchronous REST API built with `FastAPI` and `aiosqlite`.

- **Event Ingestion (`POST /events/ingest`)**: Accepts batches of events from the pipeline. It validates payloads using `Pydantic` schemas, applies idempotency (via unique UUID `event_id`), and inserts them into an asynchronous SQLite database.
- **Data Integration**: Merges the spatial event data with point-of-sale (POS) data (from `pos_transactions.csv`) based on store location and temporal proximity.
- **Metrics Engine**:
  - *Funnel*: Correlates `ENTRY` -> `ZONE_ENTER` -> `BILLING_QUEUE_JOIN` -> `Transaction` (via POS correlation) to identify drop-off rates at each stage of the retail journey.
  - *Heatmap*: Computes a normalized score (0-100) per zone based on dwell times and unique visitor counts, applying a statistical confidence threshold based on sample sizes.
  - *Anomalies*: Uses rule-based sliding window analysis to detect queue spikes (depth > 2x average), conversion drops, and "dead zones" (no traffic for > 30 minutes).
- **WebSocket Streaming**: Exposes real-time metric updates to connected clients (like the frontend dashboard) by broadcasting state changes.

## 3. Data Model
To ensure high write-throughput while enabling complex analytical reads, the database uses a denormalized schema for events:
- `events` table: Captures `event_id` (PK), `timestamp`, `visitor_id`, `event_type`, `zone_id`, `dwell_ms`, and an extensible `metadata_json` field.
- `pos_transactions` table: Captures transaction history.

## 4. Dashboard (`/dashboard`)
A Vanilla HTML/JS frontend utilizing a modern glassmorphism design system. It avoids heavy framework overhead while delivering a responsive, real-time interface using `Chart.js` (if needed) and native WebSockets.

## 5. AI-Assisted Decisions
Throughout the development of this pipeline, I heavily leveraged LLM assistants (like Claude and ChatGPT) to shape the architecture and solve complex Edge Cases. Here are three key areas where AI shaped the design:

1. **Mirror Reflection Filtering**
   - *AI Suggestion*: Initially, I prompted the AI to help me train a custom classifier to detect reflections. The AI suggested an alternative: since reflections appear "behind" a wall in the 2D image, their anchor points (feet) map to coordinates outside the valid floor plan polygons.
   - *My Decision*: I agreed and implemented the "Floor Filter" logic in `zone_classifier.py`, replacing a heavy ML solution with a zero-cost geometric check.
2. **Re-Identification (Re-ID)**
   - *AI Suggestion*: I asked the AI how to handle the `REENTRY` edge case when ByteTrack drops a track. The AI suggested implementing an entire OSNet Re-ID neural network.
   - *My Decision*: I **overrode** the AI. Running a second deep learning model would be too slow for a local setup. Instead, I prompted the AI to write a lightweight HSV Color Histogram matching algorithm using `cv2.compareHist`, which successfully maintained identity without the performance hit.
3. **Cross-Camera Deduplication**
   - *AI Suggestion*: The AI suggested merging tracks spatially by projecting camera views into a global 3D coordinate space.
   - *My Decision*: I **overrode** this as it was overly complex for the hackathon time constraints. Instead, I built a temporal deduplication engine in `app/ingestion.py` that merges IDs if an EXIT on one camera happens within 15 seconds of an ENTRY on another.
