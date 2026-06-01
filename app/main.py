"""
Store Intelligence API — FastAPI Application
Main entry point with structured logging, CORS, exception handling, and WebSocket support.
"""
import logging
import sys
import time
import uuid
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .database import init_db, close_db
from . import database as db
from .ingestion import router as ingestion_router
from .metrics import router as metrics_router
from .funnel import router as funnel_router
from .heatmap import router as heatmap_router
from .anomalies import router as anomalies_router
from .health import router as health_router


# --- Structured Logging Setup ---
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Add extra fields if present
        for field in ("trace_id", "store_id", "endpoint", "latency_ms", "event_count", "status_code"):
            if hasattr(record, field):
                log_entry[field] = getattr(record, field)
        return json.dumps(log_entry)


def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])


setup_logging()
logger = logging.getLogger("store_intelligence")


import asyncio
from .metrics import get_store_metrics

# --- App Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Store Intelligence API...")
    await init_db()
    logger.info("Database initialized. API ready.")
    
    # Start background broadcaster
    task = asyncio.create_task(metrics_broadcaster())
    
    yield
    
    task.cancel()
    logger.info("Shutting down...")
    await close_db()


async def metrics_broadcaster():
    """Poll metrics and broadcast to WebSockets every 2 seconds."""
    last_count = -1
    while True:
        try:
            if connected_clients:
                # Check if there are new events to avoid unnecessary calculation
                cursor = await db._db_pool.execute("SELECT COUNT(*) FROM events")
                current_count = (await cursor.fetchone())[0]
                
                if current_count != last_count:
                    last_count = current_count
                    # Fetch fresh metrics
                    metrics = await get_store_metrics("STORE_BLR_002")
                    await broadcast_update({
                        "type": "METRICS_UPDATE",
                        "data": metrics.model_dump()
                    })
        except Exception as e:
            logger.error(f"Broadcaster error: {e}")
            
        await asyncio.sleep(2.0)

# --- FastAPI App ---
app = FastAPI(
    title="Store Intelligence API",
    description="Real-time store analytics from CCTV detection pipeline — Purplle Tech Challenge 2026",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request Logging Middleware ---
@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = str(uuid.uuid4())[:8]
    request.state.trace_id = trace_id
    start = time.time()

    try:
        response = await call_next(request)
    except Exception as e:
        latency_ms = round((time.time() - start) * 1000, 2)
        logger.error(
            f"Request failed: {request.method} {request.url.path}",
            extra={
                "trace_id": trace_id,
                "endpoint": request.url.path,
                "latency_ms": latency_ms,
                "status_code": 500,
            },
        )
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "trace_id": trace_id},
        )

    latency_ms = round((time.time() - start) * 1000, 2)
    logger.info(
        f"{request.method} {request.url.path} -> {response.status_code}",
        extra={
            "trace_id": trace_id,
            "endpoint": request.url.path,
            "latency_ms": latency_ms,
            "status_code": response.status_code,
        },
    )
    response.headers["X-Trace-ID"] = trace_id
    return response


# --- Exception Handlers ---
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", "unknown")
    logger.error(f"Unhandled exception: {exc}", extra={"trace_id": trace_id})
    return JSONResponse(
        status_code=503,
        content={
            "error": "Service temporarily unavailable",
            "detail": str(exc),
            "trace_id": trace_id,
        },
    )


# --- WebSocket for Live Dashboard ---
connected_clients: list[WebSocket] = []


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info(f"WebSocket client connected. Total: {len(connected_clients)}")
    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(connected_clients)}")


async def broadcast_update(data: dict):
    """Broadcast metrics update to all connected dashboard clients."""
    message = json.dumps(data)
    disconnected = []
    for client in connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        connected_clients.remove(client)


# --- Register Routers ---
app.include_router(ingestion_router, tags=["Ingestion"])
app.include_router(metrics_router, tags=["Metrics"])
app.include_router(funnel_router, tags=["Funnel"])
app.include_router(heatmap_router, tags=["Heatmap"])
app.include_router(anomalies_router, tags=["Anomalies"])
app.include_router(health_router, tags=["Health"])


# --- Root endpoint ---
@app.get("/")
async def root():
    return {
        "service": "Store Intelligence API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


# Try to mount static files for dashboard
import os
dashboard_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard")
if os.path.exists(dashboard_path):
    app.mount("/dashboard", StaticFiles(directory=dashboard_path, html=True), name="dashboard")
