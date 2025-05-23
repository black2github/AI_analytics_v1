# app/routes/analyze.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from app.rag_pipeline import analyze_text, analyze_pages
from app.embedding_store import get_vectorstore

router = APIRouter()


class AnalyzeTextRequest(BaseModel):
    text: str


class AnalyzePagesRequest(BaseModel):
    page_ids: List[str]


@router.post("/analyze")
async def analyze_endpoint(request: AnalyzeTextRequest):
    try:
        platform_store = get_vectorstore("platform")
        service_store = get_vectorstore("service")
        result = analyze_text(request.text, platform_store, service_store)
        return {"status": "success", "analysis": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze_service_pages")
async def analyze_service_pages(request: AnalyzePagesRequest):
    try:
        result = analyze_pages(request.page_ids)
        return {"status": "success", "analysis": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
