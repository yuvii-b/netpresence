import logging

from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

logger = logging.getLogger("netpresence.db")

class Database:
    client: AsyncIOMotorClient = None
    db = None

db_instance = Database()

async def connect_to_mongo():
    db_instance.client = AsyncIOMotorClient(settings.MONGO_URL)
    db_instance.db = db_instance.client[settings.DB_NAME]
    await db_instance.db.sessions.create_index("session_id", unique=True)
    await db_instance.db.attendance.create_index(
        [("session_id", 1), ("student_id", 1)], unique=True
    )
    logger.info("Connected to MongoDB.")

async def close_mongo_connection():
    if db_instance.client:
        db_instance.client.close()
        logger.info("Closed MongoDB connection.")