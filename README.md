# 🏪 Store Intelligence System

> A containerised, real-time analytics pipeline that transforms raw CCTV footage into actionable retail intelligence — built for the **Purplle Tech Challenge 2026**.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Algorithmic Design](#algorithmic-design)
  - [1. Object Detection — YOLOv8 Nano](#1-object-detection--yolov8-nano)
  - [2. Multi-Object Tracking — ByteTrack](#2-multi-object-tracking--bytetrack)
  - [3. Zone Classification — Ray-Casting Point-in-Polygon](#3-zone-classification--ray-casting-point-in-polygon)
  - [4. Mirror / Reflection Filtering — Floor Filter](#4-mirror--reflection-filtering--floor-filter)
  - [5. Re-Identification — HSV Color Histogram Matching](#5-re-identification--hsv-color-histogram-matching)
  - [6. Staff Detection — Multi-Signal Heuristic Classifier](#6-staff-detection--multi-signal-heuristic-classifier)
  - [7. Entry / Exit Detection — Virtual Tripwire](#7-entry--exit-detection--virtual-tripwire)
  - [8. Cross-Camera Deduplication — Temporal Window Merge](#8-cross-camera-deduplication--temporal-window-merge)
  - [9. Conversion Funnel — Session-Based Stage Correlation](#9-conversion-funnel--session-based-stage-correlation)
  - [10. Heatmap Scoring — Weighted Normalisation](#10-heatmap-scoring--weighted-normalisation)
  - [11. Anomaly Detection — Rule-Based Sliding Window](#11-anomaly-detection--rule-based-sliding-window)
- [Data Flow](#data-flow)
- [Event Schema Design](#event-schema-design)
- [API Endpoints](#api-endpoints)
- [Tech Stack & Justifications](#tech-stack--justifications)
- [Project Structure](#project-structure)
- [Instructions to Run](#instructions-to-run)
- [Running Tests](#running-tests)

---

## System Architecture

The system is divided into two **decoupled subsystems** connected by a REST API boundary:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        STORE INTELLIGENCE SYSTEM                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │              SUBSYSTEM 1 — VIDEO ANALYTICS PIPELINE                 │     │
│  │                         (Edge / Local)                              │     │
│  │                                                                     │     │
│  │  ┌──────────┐   ┌───────────┐   ┌──────────────┐    ┌────────────┐  │     │
│  │  │  CCTV    │──▶│  YOLOv8   │──▶│  ByteTrack   │──▶│   Zone    │  │     │
│  │  │  Feeds   │   │  Nano     │   │  Tracker      │   │ Classifier │  │     │
│  │  │ (5 Cams) │   │ (Person   │   │ (Persistent   │   │ (Ray-Cast  │  │     │
│  │  └──────────┘   │  Detect)  │   │  Track IDs)   │   │  PiP)      │  │     │
│  │                 └───────────┘   └───────────────┘   └──────┬─────┘  │     │
│  │                                                            │        │     │
│  │                 ┌───────────┐   ┌───────────────┐          │        │     │
│  │                 │  Staff    │◀──│  Floor Filter │◀────────┘        │     │
│  │                 │ Detector  │   │ (Reflection    │                  │     │
│  │                 │(Heuristic)│   │  Rejection)    │                  │     │
│  │                 └─────┬─────┘   └───────────────┘                   │     │
│  │                       │                                             │     │
│  │                       ▼                                             │     │
│  │              ┌─────────────────┐   ┌────────────────┐               │     │
│  │              │  Event Emitter  │──▶│  events.jsonl  │              │     │
│  │              │  (Structured    │   │  (JSONL File)  │               │     │
│  │              │   JSONL Output) │   └────────────────┘               │     │
│  │              └────────┬────────┘                                    │     │
│  └───────────────────────┼────────────────────────────────────────────┘      │
│                          │  POST /events/ingest (Batch, Idempotent)          │
│                          ▼                                                   │
│  ┌────────────────────────────────────────────────────────────────────────┐
│  │              SUBSYSTEM 2 — INTELLIGENCE API                        │  │
│  │                    (Dockerised Backend)                            │  │
│  │                                                                    │  │
│  │  ┌──────────────┐   ┌─────────────┐    ┌─────────────────────────┐ │  │
│  │  │  FastAPI      │   │  aiosqlite  │   │  POS Data Integration   │ │  │
│  │  │  + Pydantic   │──▶│  (Async    │◀──│  (CSV → DB on startup)  │ │  │
│  │  │  Validation   │   │   SQLite)  │   └─────────────────────────┘  │  │
│  │  └──────┬────────┘   └─────┬──────┘                                │  │
│  │         │                  │                                       │  │
│  │         ▼                  ▼                                       │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────┐  │  │
│  │  │ Metrics  │  │  Funnel  │  │ Heatmap  │  │ Anomaly Detection │   │  │
│  │  │ Engine   │  │ Analysis │  │ Scoring  │  │ (Rule-based)      │   │  │
│  │  └────┬─────┘  └──────────┘  └──────────┘  └────────────────────┘  │  │
│  │       │                                                            │  │
│  │       ▼   WebSocket /ws/live (2s broadcast interval)               │  │
│  │  ┌────────────────────────────────────────────────┐                │  │
│  │  │        LIVE DASHBOARD (Vanilla JS)             │                │  │
│  │  │  Glassmorphism UI  •  Chart.js  •  WebSocket   │                │  │
│  │  └────────────────────────────────────────────────┘                │  │
│  └─────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

### Why this architecture?

| Decision | Choice | Reasoning |
|---|---|---|
| **Decoupled pipeline ↔ API** | REST boundary (`POST /events/ingest`) | The CV pipeline is compute-heavy and runs on the host GPU. The API is lightweight and runs in Docker. Decoupling lets them scale and fail independently. |
| **Edge-first processing** | Semantic events emitted at the pipeline, not raw coordinates | Pushing spatial reasoning to the edge reduces API payload by 100×. Only meaningful state changes (ENTRY, ZONE_ENTER, etc.) cross the network. |
| **SQLite over Postgres** | `aiosqlite` with WAL mode | A single `docker compose up` must work on a reviewer's laptop. No Zookeeper, no Kafka, no Postgres containers — just a single file DB. |
| **WebSocket broadcasting** | 2-second polling with dirty-check | The dashboard needs real-time feel without overwhelming the client. The broadcaster only recomputes metrics when the event count changes. |

---

## Algorithmic Design

### 1. Object Detection — YOLOv8 Nano

**Algorithm:** Single-stage anchor-free object detector (Ultralytics YOLOv8n).

**How it works:**
- The input frame is passed through a CSPDarknet53 backbone, a Feature Pyramid Network (FPN) neck, and a decoupled detection head.
- The model outputs bounding boxes, class probabilities, and objectness scores in a single forward pass.
- We filter for `class=0` (person) with a confidence threshold of `0.3`.

**Why YOLOv8 Nano:**
| Alternative | Why Rejected |
|---|---|
| **RT-DETR** | Higher accuracy on occluded figures, but ~3× slower inference. Requires heavy GPU acceleration that a hackathon reviewer's laptop may not have. |
| **MediaPipe** | Designed for single-person pose estimation, not multi-person retail tracking. |
| **YOLOv8-Large** | Better accuracy but 10× heavier. Nano achieves sufficient person-detection accuracy at 30+ FPS on consumer hardware. |

**Config:** Processes every 3rd frame (`skip_frames=3`) to maintain real-time throughput without sacrificing tracking continuity.

---

### 2. Multi-Object Tracking — ByteTrack

**Algorithm:** ByteTrack (Zhang et al., ECCV 2022) — a multi-object tracker that associates **every** detection box, including low-confidence ones.

**How it works:**
1. **First association:** High-confidence detections (`> 0.5`) are matched to existing tracks using IoU (Intersection over Union) with the Hungarian algorithm.
2. **Second association:** Remaining unmatched tracks are re-matched against *low-confidence* detections (`> 0.1`). This is ByteTrack's key innovation — it rescues occluded persons that other trackers would discard.
3. **Track lifecycle:** New tracks are created when detections exceed `new_track_thresh=0.6`. Lost tracks are kept in a buffer for 150 frames (~5 seconds at 30fps) before deletion, allowing re-association after brief occlusions.

**Why ByteTrack:**
| Alternative | Why Rejected |
|---|---|
| **SORT / DeepSORT** | SORT uses only IoU for association and drops heavily occluded targets. DeepSORT adds a Re-ID CNN per detection, which doubles inference time. |
| **StrongSORT** | Uses OSNet appearance features — adds a second deep learning model per frame, too slow for local deployment. |
| **ByteTrack** ✅ | Uses low-confidence detections for recovery (perfect for crowded retail shelves), requires zero additional neural networks, and is natively integrated into Ultralytics. |

**Custom tuning** (`custom_tracker.yaml`):
```yaml
track_buffer: 150   # Keep lost tracks for ~5 seconds (default 30)
match_thresh: 0.8   # Stricter IoU matching to avoid ID swaps
new_track_thresh: 0.6  # Only create tracks from confident detections
```

---

### 3. Zone Classification — Ray-Casting Point-in-Polygon

**Algorithm:** Ray-casting algorithm for point-in-polygon (PiP) membership testing.

**How it works:**
1. The bounding box's **bottom-center** pixel (representing the person's feet on the floor) is extracted.
2. Pixel coordinates are **normalised** to `[0, 1]` relative to frame dimensions.
3. The normalised point is tested against pre-defined polygonal boundaries for each camera's visible zones using the ray-casting algorithm:
   - Cast a horizontal ray from the point to infinity.
   - Count the number of polygon edges the ray crosses.
   - **Odd crossings** → point is inside. **Even crossings** → point is outside.
4. Sub-zone resolution: If the point falls within a parent zone (e.g., SKINCARE), it is further tested against sub-zone polygons (e.g., FACE_SHOP, MINIMALIST, AQUALOGICA).

```
Zone Polygon Example (CAM_SKINCARE_01):

   (0,0)────────────────────(0.85,0)
     │    SKINCARE ZONE       │
     │  ┌──────┬──────┬─────┐ │
     │  │EB_KR │FACE_ │GOOD │ │
     │  │      │SHOP  │VIBES│ │
     │  └──────┴──────┴─────┘ │
   (0,0.7)───────────────(0.85,0.7)
                 │
        (0.45,0.7)──────────(1.0,0.7)
                 │    FOH     │
        (0.45,1.0)──────────(1.0,1.0)
```

**Why ray-casting PiP:**
- **O(n) per point** where n = number of polygon edges. With 4–6 edges per zone and ~10 zones per camera, this is negligible compared to YOLO inference.
- Zero external dependencies — pure arithmetic.
- Pixel-precise for hand-drawn polygons extracted from the floor plan.
- Avoids the overhead of spatial indexing (R-trees) or ML-based zone classification, which are overkill for ≤10 static polygons.

---

### 4. Mirror / Reflection Filtering — Floor Filter

**Algorithm:** Geometric rejection — if a detected person's feet map to coordinates **outside all valid floor polygons**, the detection is discarded.

**How it works:**
1. Retail stores have wall mirrors behind product shelves.
2. YOLO detects mirror reflections as real people (identical confidence scores).
3. However, reflections appear "behind" the wall in 2D image space — their foot-anchor coordinates fall outside the physical floor plan.
4. The Floor Filter reuses the zone classifier: if `classify_zone()` returns `(None, None)`, the detection is rejected.

**Why this approach:**
| Alternative | Why Rejected |
|---|---|
| **Train a reflection classifier** | Requires labeled dataset of reflections vs. real people. Expensive to collect, fragile across stores. |
| **Depth estimation** | Monocular depth networks (MiDaS) add inference latency and are unreliable on flat mirror surfaces. |
| **Floor Filter** ✅ | Zero-cost geometric check. Reuses existing zone polygons. 100% precision for rejecting behind-wall reflections. |

---

### 5. Re-Identification — HSV Color Histogram Matching

**Algorithm:** HSV color histogram correlation for visual appearance matching.

**How it works:**
1. When a person **exits** the store (crosses the virtual tripwire outbound on CAM 3), their image crop is converted to HSV color space and a 2D histogram (30 hue bins × 32 saturation bins) is computed and stored.
2. When a **new track** appears at the entry camera, its histogram is compared against all stored exit signatures using `cv2.compareHist` with **Pearson correlation** (`HISTCMP_CORREL`).
3. If the correlation score exceeds `0.85`, the new track is assigned the **same visitor ID** as the matched exit — preserving identity across track drops.

```
Exit event:
  Person crop → BGR→HSV → calcHist([H,S], [30,32]) → normalize → store

Re-entry event:
  New crop → BGR→HSV → calcHist([H,S], [30,32]) → normalize
  → compareHist(new_hist, stored_hist, CORREL) > 0.85 → MATCH
```

**Why HSV histogram over deep Re-ID:**
| Alternative | Why Rejected |
|---|---|
| **OSNet Re-ID** | State-of-the-art CNN for person re-identification. Adds 50ms+ per crop per frame. Running two deep learning models simultaneously would bottleneck the pipeline on consumer GPUs. |
| **Feature embeddings (CLIP)** | Powerful but massively over-parameterised for same-session Re-ID (same clothing, same lighting). |
| **HSV Histogram** ✅ | Clothing color is stable within a single shopping session. HSV is invariant to slight illumination changes. Runs in <1ms per comparison. Sufficient accuracy for same-session, same-store Re-ID. |

---

### 6. Staff Detection — Multi-Signal Heuristic Classifier

**Algorithm:** Weighted scoring across multiple behavioural and appearance signals.

**How it works:**
Each tracked person accumulates a staff score across three independent signals:

| Signal | Weight | Threshold | Rationale |
|---|---|---|---|
| **Presence duration** | +0.4 | Visible >70% of clip | Staff are present for the entire shift; customers visit briefly. |
| **Dark clothing** | +0.3 | >60% of frames show dark torso | Purplle store staff wear black uniforms. Detected by checking if >40% of torso pixels have grayscale intensity <80. |
| **Behind-counter position** | +0.3 | >70% of detections in top portion of CAM 5 | Billing staff stand behind the counter, which maps to the upper region of the billing camera's field of view. |
| **Backroom (CAM 4)** | 0.95 | Any detection | Anyone in the backroom is definitionally staff. |

**Classification rule:** `is_staff = (total_score ≥ 0.5)`

**Why heuristic over ML:**
- No labeled staff/customer dataset exists for this specific store.
- Training a binary classifier requires ground-truth annotations across multiple clips.
- The three heuristic signals are independently observable and combine with high precision for this controlled environment.

---

### 7. Entry / Exit Detection — Virtual Tripwire

**Algorithm:** Directional line-crossing detection on the entry camera (CAM 3).

**How it works:**
1. A virtual vertical line is defined at `x = 0.45` (normalised) of CAM 3's frame — aligned with the glass door threshold.
2. For each tracked person, the system compares `prev_x` and `curr_x` across consecutive frames.
3. **Right → Left** crossing (outside → inside): Emit `ENTRY` event.
4. **Left → Right** crossing (inside → outside): Emit `EXIT` event.

```
CAM 3 Frame:
  ←── INSIDE STORE ──┃── OUTSIDE ──→
                      ┃ (x = 0.45)
                      ┃
  Person moves R→L:   ┃  = ENTRY
  Person moves L→R:   ┃  = EXIT
```

**Why virtual tripwire:**
- Simple, deterministic, and zero-latency.
- No ML model required — just a coordinate comparison.
- Perfectly suited for a single-door retail store with a fixed camera angle.

---

### 8. Cross-Camera Deduplication — Temporal Window Merge

**Algorithm:** Temporal proximity matching across camera feeds.

**How it works:**
1. When a person **exits** one camera's field of view (`EXIT` or `ZONE_EXIT`), their visitor ID and timestamp are stored in a short-lived buffer.
2. When a person **enters** a different camera's field of view (`ENTRY` or `ZONE_ENTER`), the buffer is checked for recent exits from other cameras.
3. If an exit occurred within **15 seconds** on a different camera, the new visitor ID is mapped to the exiting visitor's ID.
4. Old entries are pruned from the buffer every ingestion cycle.

**Why temporal merge over spatial projection:**
| Alternative | Why Rejected |
|---|---|
| **3D homography projection** | Requires calibrated camera intrinsics/extrinsics and a global coordinate system. Extremely complex for 5 heterogeneous cameras. |
| **Temporal window** ✅ | In a single-floor, ~1000 sq ft retail store, a person takes <15 seconds to walk between any two camera zones. The 15-second window is empirically tight enough to avoid false merges while catching real transitions. |

---

### 9. Conversion Funnel — Session-Based Stage Correlation

**Algorithm:** Four-stage session funnel with POS temporal correlation.

**How it works:**
```
Stage 1: ENTRY          — Unique visitors who triggered an ENTRY event on CAM 3
    ↓ (drop-off %)
Stage 2: ZONE VISIT     — Visitors who entered at least one product zone
                           (SKINCARE, MAKEUP, FRAGRANCE, ACCESSORIES, etc.)
    ↓ (drop-off %)
Stage 3: BILLING QUEUE  — Visitors detected in the BILLING zone or who
                           triggered BILLING_QUEUE_JOIN
    ↓ (drop-off %)
Stage 4: PURCHASE       — Visitors in BILLING zone within a 5-minute window
                           before a POS transaction timestamp
```

**POS Correlation Logic:**
- For each POS transaction, a 5-minute lookback window is created.
- Any visitor detected in the BILLING zone within that window is marked as "converted."
- This avoids requiring a 1:1 mapping between visitor IDs and transaction IDs (which is impossible without loyalty cards).

**Why session-based over event-counting:**
- Counting raw events would inflate numbers (one person triggers multiple ZONE_ENTER events).
- Session-based deduplication ensures each visitor is counted **once** per funnel stage, producing accurate drop-off percentages.

---

### 10. Heatmap Scoring — Weighted Normalisation

**Algorithm:** Composite zone scoring with visit frequency and dwell time.

**Formula:**
```
normalised_score = 0.7 × (visit_count / max_visits × 100)
                 + 0.3 × (avg_dwell_ms / max_dwell_ms × 100)
```

**Why 70/30 weighting:**
- **Visit count (70%):** The primary indicator of zone attractiveness. High footfall = high interest.
- **Dwell time (30%):** A secondary signal that differentiates "passing through" from "engaged browsing." A zone with fewer visitors but long dwell times (e.g., fragrance sampling) should still rank meaningfully.
- **Data confidence flag:** Zones with fewer than 20 sessions are marked `data_confidence: false` to warn the dashboard consumer that the score may be unreliable.

---

### 11. Anomaly Detection — Rule-Based Sliding Window

**Algorithm:** Threshold-based anomaly triggers with severity classification.

| Anomaly Type | Detection Rule | Severity |
|---|---|---|
| **BILLING_QUEUE_SPIKE** | Current queue depth > 2× average AND depth ≥ 3 | WARN (2×), CRITICAL (3×) |
| **CONVERSION_DROP** | Conversion rate < 10% with ≥ 10 visitors | WARN (>5%), CRITICAL (≤5%) |
| **DEAD_ZONE** | No ZONE_ENTER or ZONE_DWELL events for > 30 min | INFO (<60 min), WARN (≥60 min) |
| **HIGH_ABANDONMENT** | Queue abandonment rate > 30% with ≥ 3 joins | WARN (<50%), CRITICAL (≥50%) |

Each anomaly includes a human-readable `suggested_action` for store managers (e.g., "Open additional billing counter").

**Why rule-based over ML anomaly detection:**
- Statistical anomaly detectors (Isolation Forest, Autoencoders) require historical training data spanning weeks/months.
- The 2-minute CCTV clips provide insufficient data volume for ML-based baselines.
- Rule-based thresholds are **interpretable**, **tunable**, and produce actionable alerts with zero training time.

---

## Data Flow

```
CCTV .mp4 files
      │
      ▼
┌─────────────────┐     Every 3rd frame
│  YOLOv8n Detect │────────────────────▶ Bounding boxes + confidence
│  (class=person) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   ByteTrack     │────────────────────▶ Persistent track IDs
│   (IoU + low-   │
│    conf rescue) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Floor Filter   │──── Reflection? ──▶ DISCARD
│  (PiP check)    │──── Valid floor ──▶ continue
└────────┬────────┘
         │
    ┌────┴─────┐
    ▼          ▼
┌────────┐ ┌──────────┐
│Entry/  │ │Zone      │
│Exit    │ │Classify  │──▶ ZONE_ENTER / ZONE_EXIT / ZONE_DWELL
│Tripwire│ │(PiP)     │
└───┬────┘ └──────────┘
    │
    ▼
ENTRY / EXIT / REENTRY events
    │
    ▼
┌─────────────────┐
│  Staff Detector │──▶ is_staff flag on each event
│  (heuristic)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Event Emitter  │──▶ events.jsonl (+ live POST to API)
│  (JSONL + HTTP) │
└────────┬────────┘
         │
         ▼   POST /events/ingest (batch ≤500, idempotent by event_id)
┌──────────────────┐
│  FastAPI API     │
│  + aiosqlite DB  │──▶ Metrics, Funnel, Heatmap, Anomalies
│  + POS CSV data  │──▶ WebSocket broadcast to Dashboard
└──────────────────┘
```

---

## Event Schema Design

We chose a **Sparse Semantic Schema** — only meaningful state transitions are emitted:

```json
{
  "event_id": "uuid-v4",
  "store_id": "STORE_BLR_002",
  "camera_id": "CAM_SKINCARE_01",
  "visitor_id": "VIS_a3f2c1",
  "event_type": "ZONE_ENTER",
  "timestamp": "2026-04-10T20:09:45Z",
  "zone_id": "SKINCARE",
  "dwell_ms": 0,
  "is_staff": false,
  "confidence": 0.8721,
  "metadata": {
    "queue_depth": null,
    "sku_zone": "FACE_SHOP",
    "session_seq": 3
  }
}
```

**Valid event types:** `ENTRY` · `EXIT` · `REENTRY` · `ZONE_ENTER` · `ZONE_EXIT` · `ZONE_DWELL` · `BILLING_QUEUE_JOIN` · `BILLING_QUEUE_ABANDON`

**Why sparse over dense:**
A dense schema (emitting x,y every second per person) would generate ~100,000+ events/hour and overwhelm SQLite. By pushing spatial reasoning to the edge pipeline, only ~500 semantic events are generated per camera clip — keeping the API fast and the database lean.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/events/ingest` | Batch-ingest up to 500 events (idempotent by `event_id`) |
| `GET` | `/stores/{store_id}/metrics` | Real-time KPIs: visitors, conversion rate, revenue, queue depth |
| `GET` | `/stores/{store_id}/funnel` | 4-stage conversion funnel with drop-off percentages |
| `GET` | `/stores/{store_id}/heatmap` | Zone visit frequency + dwell, normalised 0–100 |
| `GET` | `/stores/{store_id}/anomalies` | Active anomalies with severity + suggested actions |
| `GET` | `/health` | System health, per-store feed status, event lag detection |
| `WS` | `/ws/live` | WebSocket for real-time dashboard metric broadcasts |

---

## Tech Stack & Justifications

| Component | Technology | Why |
|---|---|---|
| **Object Detection** | YOLOv8 Nano (Ultralytics) | Best speed/accuracy trade-off for consumer GPU. Single-stage, anchor-free, natively supports tracking. |
| **Tracker** | ByteTrack | Rescues occluded detections via low-confidence second association. Zero additional neural networks. |
| **Backend API** | FastAPI + Pydantic | Async-native, auto-generated OpenAPI docs, strict schema validation. |
| **Database** | aiosqlite (SQLite + WAL) | Single-file DB. No infra dependencies. Async for non-blocking API. Perfect for `docker compose up` deployments. |
| **Re-ID** | OpenCV HSV Histogram | <1ms per comparison. Sufficient for same-session, same-clothing Re-ID without a second deep learning model. |
| **Dashboard** | Vanilla HTML/CSS/JS | No build step, no npm, no webpack. Loads instantly. Glassmorphism design with WebSocket real-time updates. |
| **Containerisation** | Docker + docker-compose | One command to deploy. Health checks included. Volume-mounts for persistent data. |
| **Testing** | pytest + fixtures | Comprehensive test suite covering ingestion, metrics, anomalies, and pipeline logic. |

---

## Project Structure

```
store-intelligence/
├── app/                        # FastAPI application
│   ├── main.py                 # App entry point, lifespan, WebSocket, middleware
│   ├── models.py               # Pydantic schemas (StoreEvent, StoreMetrics, etc.)
│   ├── database.py             # aiosqlite layer, schema init, POS data loading
│   ├── ingestion.py            # POST /events/ingest — batch, idempotent, dedup
│   ├── metrics.py              # GET /metrics — real-time KPIs with POS correlation
│   ├── funnel.py               # GET /funnel — 4-stage conversion funnel
│   ├── heatmap.py              # GET /heatmap — normalised zone scoring
│   ├── anomalies.py            # GET /anomalies — rule-based detection
│   ├── health.py               # GET /health — system + feed status
│   └── seed.py                 # Auto-seed sample data for fresh deployments
│
├── pipeline/                   # Video analytics pipeline (runs on host)
│   ├── detect.py               # Main pipeline: YOLO → ByteTrack → Zone → Emit
│   ├── zone_classifier.py      # Ray-casting PiP with per-camera polygon maps
│   ├── staff_detector.py       # Multi-signal heuristic staff classifier
│   ├── emit.py                 # JSONL event emitter with live HTTP streaming
│   ├── ingest_events.py        # Batch POST events.jsonl → API
│   ├── run.sh                  # One-shot pipeline runner
│   └── custom_tracker.yaml     # ByteTrack tuning (extended buffer, strict match)
│
├── dashboard/                  # Frontend
│   ├── index.html              # Main HTML structure
│   ├── app.js                  # WebSocket client, Chart.js integration
│   └── styles.css              # Glassmorphism design system
│
├── data/                       # Runtime data (gitignored)
│   ├── pos_transactions.csv    # POS transaction data
│   └── store_intelligence.db   # SQLite database (auto-created)
│
├── tests/                      # Test suite
│   ├── conftest.py             # Shared fixtures, mock DB, sample events
│   ├── test_ingestion.py       # Ingestion endpoint tests
│   ├── test_metrics.py         # Metrics calculation tests
│   ├── test_anomalies.py       # Anomaly detection tests
│   └── test_pipeline.py        # Pipeline unit tests
│
├── docs/                       # Additional documentation
│   ├── DESIGN.md               # Architecture deep-dive
│   └── CHOICES.md              # Technical trade-off decisions
│
├── Dockerfile                  # API container (Python 3.12-slim)
├── docker-compose.yml          # Single-command deployment
├── requirements.txt            # API dependencies
├── requirements-pipeline.txt   # CV pipeline dependencies
├── requirements-test.txt       # Test dependencies
└── .gitignore                  # Excludes videos, models, DBs, caches
```

---

## Instructions to Run

### Prerequisites
- Docker and Docker Compose
- Python 3.10+ (for running the CV pipeline locally)
- Ensure ports `8000` (API) and `8080` (Dashboard) are available.

### Option 1: Quick Start (Docker + Local Pipeline)

```bash
cd store-intelligence

# 1. Start the API and Dashboard
docker compose up --build -d

# 2. Install CV dependencies on host
pip install -r requirements-pipeline.txt

# 3. Run detection pipeline on CCTV clips
python pipeline/detect.py --video_dir "../CCTV Footage"

# 4. Ingest events into API
python pipeline/ingest_events.py

# 5. Open Dashboard
# → http://localhost:8080

# 6. API Docs
# → http://localhost:8000/docs
```

### Option 2: Fully Local (Without Docker)

```bash
# 1. Create venv
python -m venv venv
source venv/bin/activate       # Linux/Mac
venv\Scripts\activate          # Windows

# 2. Install all dependencies
pip install -r requirements.txt
pip install -r requirements-pipeline.txt

# 3. Start API server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 4. Run pipeline (in a separate terminal)
./pipeline/run.sh

# 5. Serve dashboard
cd dashboard && python -m http.server 8080
```

---

## Running Tests

```bash
pip install -r requirements-test.txt
pytest tests/ -v
```

---

## License

Built for the Purplle Tech Challenge 2026 — Round 2.
