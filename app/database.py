"""
SQLite database layer for the Store Intelligence API.
Uses aiosqlite for async operations with connection pooling.
"""
import aiosqlite
import csv
import json
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

logger = logging.getLogger("store_intelligence.db")

_db_pool: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    """Get database connection (singleton)."""
    global _db_pool
    if _db_pool is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db_pool


async def init_db():
    """Initialize database schema and load POS data."""
    global _db_pool
    db_path = os.environ.get("DB_PATH", "data/store_intelligence.db")
    pos_csv_path = os.environ.get("POS_CSV_PATH", "data/pos_transactions.csv")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    _db_pool = await aiosqlite.connect(db_path)
    _db_pool.row_factory = aiosqlite.Row

    await _db_pool.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            store_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            visitor_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            zone_id TEXT,
            dwell_ms INTEGER DEFAULT 0,
            is_staff INTEGER DEFAULT 0,
            confidence REAL DEFAULT 0.0,
            metadata_json TEXT DEFAULT '{}',
            ingested_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_events_store ON events(store_id);
        CREATE INDEX IF NOT EXISTS idx_events_visitor ON events(visitor_id);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_zone ON events(zone_id);
        CREATE INDEX IF NOT EXISTS idx_events_store_type ON events(store_id, event_type);

        CREATE TABLE IF NOT EXISTS pos_transactions (
            transaction_id TEXT PRIMARY KEY,
            store_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            basket_value_inr REAL DEFAULT 0.0
        );

        CREATE INDEX IF NOT EXISTS idx_pos_store ON pos_transactions(store_id);
        CREATE INDEX IF NOT EXISTS idx_pos_timestamp ON pos_transactions(timestamp);
    """)

    # Load POS data if table is empty
    cursor = await _db_pool.execute("SELECT COUNT(*) FROM pos_transactions")
    count = (await cursor.fetchone())[0]
    if count == 0 and pos_csv_path and os.path.exists(pos_csv_path):
        logger.info(f"Loading POS transactions from {pos_csv_path}")
        with open(pos_csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                await _db_pool.execute(
                    "INSERT OR IGNORE INTO pos_transactions (transaction_id, store_id, timestamp, basket_value_inr) VALUES (?, ?, ?, ?)",
                    (row["transaction_id"], row["store_id"], row["timestamp"], float(row["basket_value_inr"]))
                )
        await _db_pool.commit()
        logger.info("POS transactions loaded.")

    await _db_pool.commit()
    logger.info(f"Database initialized at {db_path}")


async def close_db():
    """Close database connection."""
    global _db_pool
    if _db_pool:
        await _db_pool.close()
        _db_pool = None
        logger.info("Database connection closed.")


async def insert_event(event_dict: dict) -> bool:
    """
    Insert a single event. Returns True if inserted, False if duplicate (idempotent).
    """
    db = await get_db()
    try:
        metadata_json = json.dumps(event_dict.get("metadata", {}))
        await db.execute(
            """INSERT OR IGNORE INTO events
            (event_id, store_id, camera_id, visitor_id, event_type, timestamp, zone_id, dwell_ms, is_staff, confidence, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_dict["event_id"],
                event_dict["store_id"],
                event_dict["camera_id"],
                event_dict["visitor_id"],
                event_dict["event_type"],
                event_dict["timestamp"],
                event_dict.get("zone_id"),
                event_dict.get("dwell_ms", 0),
                1 if event_dict.get("is_staff", False) else 0,
                event_dict.get("confidence", 0.0),
                metadata_json,
            ),
        )
        await db.commit()
        return db.total_changes > 0
    except Exception as e:
        logger.error(f"Error inserting event {event_dict.get('event_id')}: {e}")
        return False


async def get_events_by_store(store_id: str, event_type: str | None = None,
                               exclude_staff: bool = True) -> list[dict]:
    """Get events for a store, optionally filtered by type."""
    db = await get_db()
    query = "SELECT * FROM events WHERE store_id = ?"
    params = [store_id]

    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    if exclude_staff:
        query += " AND is_staff = 0"

    query += " ORDER BY timestamp ASC"

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_unique_visitors(store_id: str) -> int:
    """Count unique non-staff visitors."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(DISTINCT visitor_id) FROM events WHERE store_id = ? AND is_staff = 0 AND event_type = 'ENTRY'",
        (store_id,)
    )
    return (await cursor.fetchone())[0]


async def get_pos_transactions(store_id: str) -> list[dict]:
    """Get POS transactions for a store."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM pos_transactions WHERE store_id = ? ORDER BY timestamp ASC",
        (store_id,)
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_zone_dwell_stats(store_id: str) -> dict:
    """Get average dwell time per zone."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT zone_id, AVG(dwell_ms) as avg_dwell, COUNT(*) as count
        FROM events
        WHERE store_id = ? AND event_type = 'ZONE_DWELL' AND is_staff = 0 AND zone_id IS NOT NULL
        GROUP BY zone_id""",
        (store_id,)
    )
    rows = await cursor.fetchall()
    return {row["zone_id"]: {"avg_dwell_ms": row["avg_dwell"], "count": row["count"]} for row in rows}


async def get_billing_queue_stats(store_id: str) -> dict:
    """Get billing queue statistics."""
    db = await get_db()

    # Latest queue depth
    cursor = await db.execute(
        """SELECT metadata_json FROM events
        WHERE store_id = ? AND event_type = 'BILLING_QUEUE_JOIN'
        ORDER BY timestamp DESC LIMIT 1""",
        (store_id,)
    )
    row = await cursor.fetchone()
    queue_depth = 0
    if row:
        meta = json.loads(row["metadata_json"])
        queue_depth = meta.get("queue_depth", 0)

    # Join count
    cursor = await db.execute(
        "SELECT COUNT(*) FROM events WHERE store_id = ? AND event_type = 'BILLING_QUEUE_JOIN' AND is_staff = 0",
        (store_id,)
    )
    join_count = (await cursor.fetchone())[0]

    # Abandon count
    cursor = await db.execute(
        "SELECT COUNT(*) FROM events WHERE store_id = ? AND event_type = 'BILLING_QUEUE_ABANDON' AND is_staff = 0",
        (store_id,)
    )
    abandon_count = (await cursor.fetchone())[0]

    return {
        "current_queue_depth": queue_depth,
        "join_count": join_count,
        "abandon_count": abandon_count,
        "abandonment_rate": abandon_count / join_count if join_count > 0 else 0.0
    }


async def get_last_event_timestamp(store_id: str) -> str | None:
    """Get the most recent event timestamp for a store."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT MAX(timestamp) FROM events WHERE store_id = ?",
        (store_id,)
    )
    row = await cursor.fetchone()
    return row[0] if row else None


async def get_all_store_ids() -> list[str]:
    """Get all unique store IDs."""
    db = await get_db()
    cursor = await db.execute("SELECT DISTINCT store_id FROM events")
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def get_event_count(store_id: str | None = None) -> int:
    """Get total event count, optionally for a specific store."""
    db = await get_db()
    if store_id:
        cursor = await db.execute("SELECT COUNT(*) FROM events WHERE store_id = ?", (store_id,))
    else:
        cursor = await db.execute("SELECT COUNT(*) FROM events")
    return (await cursor.fetchone())[0]


async def get_visitor_sessions(store_id: str) -> dict:
    """
    Build session data per visitor: ordered list of events.
    Returns {visitor_id: [event_dicts]} for non-staff visitors.
    """
    db = await get_db()
    cursor = await db.execute(
        """SELECT * FROM events
        WHERE store_id = ? AND is_staff = 0
        ORDER BY visitor_id, timestamp ASC""",
        (store_id,)
    )
    rows = await cursor.fetchall()

    sessions = {}
    for row in rows:
        vid = row["visitor_id"]
        if vid not in sessions:
            sessions[vid] = []
        sessions[vid].append(dict(row))

    return sessions


async def get_zone_visit_counts(store_id: str) -> dict:
    """Get visit counts per zone (unique visitors)."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT zone_id, COUNT(DISTINCT visitor_id) as unique_visitors, COUNT(*) as total_events
        FROM events
        WHERE store_id = ? AND event_type = 'ZONE_ENTER' AND is_staff = 0 AND zone_id IS NOT NULL
        GROUP BY zone_id""",
        (store_id,)
    )
    rows = await cursor.fetchall()
    return {row["zone_id"]: {"unique_visitors": row["unique_visitors"], "total_events": row["total_events"]} for row in rows}
