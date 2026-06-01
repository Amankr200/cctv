"""
Pydantic models for the Store Intelligence event schema.
Shared between the detection pipeline (emit.py) and the API (ingestion).
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from enum import Enum
from datetime import datetime
import uuid


class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int = 0


class StoreEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: EventType
    timestamp: str  # ISO-8601 UTC
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v):
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"Invalid ISO-8601 timestamp: {v}")
        return v

    @field_validator("event_id")
    @classmethod
    def validate_uuid(cls, v):
        try:
            uuid.UUID(v, version=4)
        except ValueError:
            raise ValueError(f"event_id must be a valid UUID v4: {v}")
        return v


class IngestRequest(BaseModel):
    events: list[StoreEvent] = Field(max_length=500)


class IngestResponse(BaseModel):
    accepted: int
    rejected: int
    errors: list[dict] = []


class StoreMetrics(BaseModel):
    store_id: str
    timestamp: str
    unique_visitors: int
    conversion_rate: float
    avg_dwell_by_zone: dict[str, float]  # zone_id -> avg dwell ms
    current_queue_depth: int
    abandonment_rate: float
    total_transactions: int
    total_revenue: float


class FunnelStage(BaseModel):
    stage: str
    count: int
    drop_off_pct: float


class FunnelResponse(BaseModel):
    store_id: str
    stages: list[FunnelStage]


class HeatmapZone(BaseModel):
    zone_id: str
    zone_name: str
    visit_count: int
    avg_dwell_ms: float
    normalized_score: float  # 0-100
    data_confidence: bool  # true if >= 20 sessions


class HeatmapResponse(BaseModel):
    store_id: str
    zones: list[HeatmapZone]


class AnomalySeverity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class Anomaly(BaseModel):
    anomaly_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    store_id: str
    anomaly_type: str
    severity: AnomalySeverity
    description: str
    suggested_action: str
    detected_at: str
    metadata: dict = {}


class AnomalyResponse(BaseModel):
    store_id: str
    anomalies: list[Anomaly]


class StoreHealth(BaseModel):
    store_id: str
    status: str  # "OK", "STALE_FEED", "ERROR"
    last_event_timestamp: Optional[str] = None
    event_count: int = 0
    lag_seconds: Optional[float] = None


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    stores: list[StoreHealth]
