import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.mongo import connect_to_mongo, close_mongo_connection
from app.routers import acoustic, auth, devices, me, sessions, teacher

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("netpresence")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()

app = FastAPI(title="NetPresence API", lifespan=lifespan)

# No auth/cookies are in play yet, so origins are left open; revisit alongside
# the Week 5-6 auth work rather than combining wildcard origins with credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],   # includes X-Teacher-Token
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


app.include_router(devices.router)
app.include_router(sessions.router)
app.include_router(acoustic.router)
app.include_router(auth.router)
app.include_router(teacher.router)
app.include_router(me.router)

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "server_time": time.time()}
