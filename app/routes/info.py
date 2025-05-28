# app/routes/info.py

import time
from datetime import datetime
from fastapi import APIRouter
import os

from app.config import APP_VERSION

START_TIME = time.time()
router = APIRouter()
uptime_seconds = int(time.time() - START_TIME)
uptime = str(datetime.utcfromtimestamp(uptime_seconds).strftime("%H:%M:%S"))


@router.get("/info")
def get_info():
    return {
        "app": "requirements-analyzer",
        "app_version": APP_VERSION,
        "git_version": os.getenv("GIT_COMMIT_SHA", "unknown"),
        "uptime": uptime,
        "description": "RAG-based AI сервис для валидации требований аналитики."
    }
