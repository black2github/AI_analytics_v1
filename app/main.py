from fastapi import FastAPI
from routes import health, analyze, loader
import logging
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Requirements RAG Analyzer")

app.include_router(health.router)
app.include_router(analyze.router)
app.include_router(loader.router)

