# app/routes/info.py

import time
from datetime import datetime, timedelta
from fastapi import APIRouter
import os
import logging

from app.config import APP_VERSION

# Время старта приложения
START_TIME = time.time()

router = APIRouter()


@router.get("/info")
def get_info():
    """Возвращает информацию о приложении."""
    # Динамическое вычисление uptime
    uptime_seconds = int(time.time() - START_TIME)
    uptime_timedelta = timedelta(seconds=uptime_seconds)

    # Форматирование uptime: дни, часы, минуты, секунды
    days = uptime_timedelta.days
    hours, remainder = divmod(uptime_timedelta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days > 0:
        uptime_str = f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    # Логирование вызова эндпоинта
    logging.info("Info endpoint called, uptime: %s", uptime_str)

    return {
        "app": "requirements-analyzer",
        "app_version": APP_VERSION,
        "git_version": os.getenv("GIT_COMMIT_SHA", "unknown"),
        "uptime": uptime_str,
        "description": "RAG-based AI сервис для валидации требований аналитики."
    }
