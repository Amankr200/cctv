# Store Intelligence System

A containerised, real-time analytics pipeline and API that transforms raw CCTV footage into actionable retail intelligence.

## Features
- **Real-time Pipeline**: Uses YOLOv8 for person detection and ByteTrack for tracking, turning video frames into structured JSONL events.
- **Store Intelligence API**: FastAPI application that ingests events, integrates with POS transaction data, and calculates live metrics, funnels, and heatmaps.
- **Live Dashboard**: Modern glassmorphism UI with WebSocket integration for real-time metric updates.
- **Anomaly Detection**: Automatically flags queue spikes, dead zones, and conversion drops.
- **Containerised**: Everything runs in Docker via `docker-compose`.

## Instructions to Run

### Prerequisites
- Docker and Docker Compose
- Ensure ports `8000` (API) and `8080` (Dashboard) are available on your host.

### Option 1: Quick Start (API in Docker, Pipeline Local)
1. Navigate to the project root directory:
   ```bash
   cd store-intelligence
   ```
2. Build and start the API and Dashboard services via Docker:
   ```bash
   docker compose up --build -d
   ```
3. Install the computer vision dependencies on your host machine:
   ```bash
   pip install -r requirements-pipeline.txt
   ```
4. Run the detection pipeline against the CCTV clips to generate events:
   ```bash
   python pipeline/detect.py --video_dir "..\CCTV Footage"
   ```
5. Ingest the generated events into the API:
   ```bash
   python pipeline/ingest_events.py
   ```
6. View the Dashboard at `http://localhost:8080`
7. Access API documentation at `http://localhost:8000/docs`

### Option 2: Local Development (Without Docker)
1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Or `venv\Scripts\activate` on Windows
   pip install -r requirements.txt
   pip install -r requirements-pipeline.txt
   ```
2. Start the API server:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
3. Run the detection pipeline:
   ```bash
   ./pipeline/run.sh
   ```
4. Ingest events:
   ```bash
   python pipeline/ingest_events.py
   ```
5. Serve the dashboard using Python's http.server:
   ```bash
   cd dashboard
   python -m http.server 8080
   ```

### Running Tests
To run the test suite locally:
```bash
pip install -r requirements-test.txt
pytest tests/ -v
```

## Structure
- `app/`: FastAPI application, endpoints, and database logic.
- `pipeline/`: YOLOv8 detection scripts, zone classification, and event emitters.
- `dashboard/`: HTML/CSS/JS frontend dashboard.
- `data/`: POS transactions, layout JSON, and SQLite database.
- `tests/`: Comprehensive pytest suite.
