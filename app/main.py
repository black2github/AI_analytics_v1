# app/maim.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import analyze, loader, info, services, health

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

