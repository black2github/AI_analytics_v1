# app/maim.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.embedding_store import get_embedding_model
from app.routes import analyze, loader, info, services, health, test_context
from app.logging_config import setup_logging

# Инициализация логирования
setup_logging()

app = FastAPI(
    title="AI Requirements Analyzer",
    description="Анализ и проверка требований на основе контекста и шаблонов",
    version="1.0.0",
)

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
@app.get("/")
async def root():
    return {"message": "Welcome to RAG Pipeline API"}

# для отладки
get_embedding_model()