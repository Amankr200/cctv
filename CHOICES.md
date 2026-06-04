# Technical Choices & Trade-offs

This document outlines the reasoning behind the three core technical decisions made for the Store Intelligence system, explicitly noting how AI shaped the final architecture.

## 1. Detection Model: YOLOv8 + ByteTrack
**Options Considered:** YOLOv8, RT-DETR, MediaPipe, OSNet (for Re-ID).
**What AI Suggested:** I prompted an LLM to evaluate detection models for a 30fps retail CCTV pipeline with heavy occlusion. The AI strongly suggested RT-DETR for higher accuracy on occluded figures and OSNet for cross-camera Re-ID.
**What I Chose & Why:** I chose **YOLOv8 Nano + ByteTrack**. While the AI was correct that RT-DETR is highly accurate, it is significantly slower and harder to deploy locally without heavy GPU acceleration. YOLOv8 provides the perfect balance of speed and accuracy, and ByteTrack handles standard occlusion perfectly without the massive overhead of OSNet. I built a custom HSV histogram Re-ID module to bridge the gap left by not using OSNet.

## 2. Event Schema Design
**Options Considered:** Dense schema (recording every `x,y` coordinate per frame) vs. Sparse schema (recording only semantic state changes).
**What AI Suggested:** When asked to design a schema for spatial retail analytics, the AI suggested a time-series heavy dense schema that emitted an event every second for every person, to perfectly track paths.
**What I Chose & Why:** I **overrode** the AI and chose a **Sparse Semantic Schema** (emitting only `ENTRY`, `ZONE_ENTER`, `ZONE_DWELL`). A dense schema would generate hundreds of thousands of events per hour per store, completely overwhelming the SQLite database and the `/events/ingest` endpoint. By pushing the spatial reasoning to the edge (the detection pipeline) and only emitting semantic state changes, the API remains blazing fast and effortlessly handles the funnel logic.

## 3. API Architecture: Event-Driven SQLite Batching
**Options Considered:** Direct PostgreSQL connection from the pipeline vs. REST API ingestion with SQLite.
**What AI Suggested:** The AI recommended using Apache Kafka for event streaming and PostgreSQL for persistent storage, citing "best practices for scalable event-driven architectures."
**What I Chose & Why:** I **overrode** the AI. Kafka and Postgres are excellent for massive cloud deployments, but this hackathon strictly requires `docker compose up` to start everything cleanly on a reviewer's local machine. Adding Zookeeper, Kafka brokers, and Postgres containers would make the setup brittle. Instead, I chose a REST API (`POST /events/ingest`) backed by an async `aiosqlite` connection pool. This achieves the required decoupling while keeping the infrastructure lightweight, deterministic, and highly portable.
