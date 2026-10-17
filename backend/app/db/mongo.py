import logging

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings

logger = logging.getLogger("netpresence.db")


class Database:
    client: AsyncIOMotorClient = None
    db = None


db_instance = Database()


async def ensure_indexes(db) -> None:
    # v2
    await db.students.create_index("student_id", unique=True)
    await db.sessions.create_index("session_id", unique=True)
    await db.checkins.create_index([("session_id", 1), ("student_id", 1)], unique=True)
    await db.checkins.create_index([("session_id", 1), ("eph_id", 1)], unique=True)
    await db.reports.create_index([("session_id", 1), ("student_id", 1)], unique=True)
    await db.attendance.create_index([("session_id", 1), ("student_id", 1)], unique=True)
    await db.device_calibration.create_index("model", unique=True)
    # v1 acoustic
    await db.acoustic_sessions.create_index("session_id", unique=True)
    await db.acoustic_attendance.create_index([("session_id", 1), ("student_id", 1)], unique=True)


async def connect_to_mongo():
    db_instance.client = AsyncIOMotorClient(settings.MONGO_URL)
    db_instance.db = db_instance.client[settings.DB_NAME]
    await ensure_indexes(db_instance.db)
    logger.info("Connected to MongoDB.")


async def close_mongo_connection():
    if db_instance.client:
        db_instance.client.close()
        logger.info("Closed MongoDB connection.")


def get_db():
    """FastAPI dependency: the active database, or 503 if not connected."""
    if db_instance.db is None:
        raise HTTPException(status_code=503, detail="Database unavailable.")
    return db_instance.db
