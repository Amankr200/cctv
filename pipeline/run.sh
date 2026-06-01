#!/bin/bash
# Run the detection pipeline on all CCTV clips
# Usage: ./run.sh [path_to_video_dir] [output_file]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

VIDEO_DIR="${1:-$PROJECT_DIR/../CCTV Footage}"
OUTPUT="${2:-$PROJECT_DIR/data/events.jsonl}"

echo "============================================"
echo "Store Intelligence Detection Pipeline"
echo "============================================"
echo "Video directory: $VIDEO_DIR"
echo "Output file: $OUTPUT"
echo ""

# Clear previous output
> "$OUTPUT"

# Run detection
cd "$PROJECT_DIR"
python -m pipeline.detect \
    --video_dir "$VIDEO_DIR" \
    --output "$OUTPUT" \
    --skip_frames 3 \
    --conf 0.3

echo ""
echo "============================================"
echo "Events generated: $(wc -l < "$OUTPUT")"
echo "Output: $OUTPUT"
echo "============================================"

# Ingest events into the API (if running)
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo ""
    echo "API detected at localhost:8000. Ingesting events..."
    python -c "
import json, requests

with open('$OUTPUT', 'r') as f:
    events = [json.loads(line) for line in f if line.strip()]

# Send in batches of 100
for i in range(0, len(events), 100):
    batch = events[i:i+100]
    resp = requests.post('http://localhost:8000/events/ingest', json={'events': batch})
    result = resp.json()
    print(f'  Batch {i//100+1}: {result[\"accepted\"]} accepted, {result[\"rejected\"]} rejected')

print(f'Total events ingested: {len(events)}')
"
else
    echo ""
    echo "API not running. Start it with: docker compose up"
    echo "Then ingest events with: python pipeline/ingest_events.py"
fi
