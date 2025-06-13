# app/routes/logging_control.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
from app.logging_utils import set_log_level, get_current_log_level, log_sample_messages

router = APIRouter()


class LogLevelRequest(BaseModel):
    level: str  # DEBUG, INFO, WARNING, ERROR, CRITICAL


@router.get("/log_level", tags=["Управление логированием"])
async def get_log_level():
    """Получает текущий уровень логирования"""
    return {"current_level": get_current_log_level()}


@router.post("/log_level", tags=["Управление логированием"])
async def change_log_level(request: LogLevelRequest):
    """Изменяет уровень логирования"""
    valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

    if request.level.upper() not in valid_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid log level. Must be one of: {valid_levels}"
        )

    try:
        set_log_level(request.level)
        return {
            "message": f"Log level changed to {request.level.upper()}",
            "previous_level": get_current_log_level()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/log_test", tags=["Управление логированием"])
async def test_logging():
    """Выводит тестовые сообщения разных уровней"""
    try:
        log_sample_messages()
        return {"message": "Test log messages sent. Check logs for output."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))