# app/main.py - обновленная версия

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.embedding_store import get_embedding_model
from app.logging_config import setup_logging
from app.routes import analyze, loader, info, services, health, test_context, logging_control

# Инициализация логирования с уровнем INFO
setup_logging()

import logging
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Requirements Analyzer",
    description="Анализ и проверка требований на основе контекста и шаблонов",
    version="1.0.0",
)

logger.info("Starting Requirements Analyzer application")

# CORS (если необходимо)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение всех маршрутов
app.include_router(analyze.router)
app.include_router(loader.router)
app.include_router(services.router)
app.include_router(health.router)
app.include_router(info.router)
app.include_router(test_context.router)
app.include_router(logging_control.router)

@app.get("/")
async def root():
    logger.info("Root endpoint accessed")
    return {"message": "Welcome to RAG Pipeline API"}

# Для отладки
try:
    get_embedding_model()
    logger.info("Embedding model initialized successfully")
except Exception as e:
    logger.error("Failed to initialize embedding model: %s", str(e))