# app/routes/analyze.py

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
import logging

from app.rag_pipeline import analyze_text, analyze_pages, analyze_with_templates
from app.service_registry import is_valid_service

router = APIRouter()

class AnalyzeTextRequest(BaseModel):
    text: str
    prompt_template: Optional[str] = None
    service_code: Optional[str] = None


class AnalyzePagesRequest(BaseModel):
    page_ids: List[str]
    prompt_template: Optional[str] = None
    service_code: Optional[str] = None


class AnalyzeWithTemplatesRequest(BaseModel):
    items: List[dict]  # Each item: {"requirement_type": str, "page_id": str}
    prompt_template: Optional[str] = None
    service_code: Optional[str] = None


class AnalyzeServicePagesRequest(BaseModel):
    page_ids: List[str]
    prompt_template: Optional[str] = None


@router.post("/analyze", tags=["Анализ текстовых требований сервиса"])
async def analyze_from_text(payload: AnalyzeTextRequest):
    try:
        result = analyze_text(
            text=payload.text,
            prompt_template=payload.prompt_template,
            service_code=payload.service_code
        )
        return {"result": result}
    except Exception as e:
        logging.exception("Ошибка в /analyze")
        return {"error": str(e)}


@router.post("/analyze_pages", tags=["Анализ существующих (ранее) требований сервиса"])
async def analyze_service_pages(payload: AnalyzePagesRequest):
    try:
        result = analyze_pages(
            page_ids=payload.page_ids,
            prompt_template=payload.prompt_template,
            service_code=payload.service_code
        )
        return {"results": result}
    except Exception as e:
        logging.exception("Ошибка в /analyze_pages")
        return {"error": str(e)}


@router.post("/analyze_service_pages/{code}", tags=["Анализ существующих (ранее) требований конкретного сервиса"])
async def analyze_service_pages(code: str, payload: AnalyzeServicePagesRequest):
    logging.info("[analyze_service_pages] <- code=%s", code)
    if not is_valid_service(code):
        return {"error": f"Сервис с кодом {code} не найден"}

    try:
        result = analyze_pages(
            page_ids=payload.page_ids,
            prompt_template=payload.prompt_template,
            service_code=code
        )
        logging.info("[analyze_service_pages] -> result={%s}", result)
        return {"results": result}
    except Exception as e:
        logging.exception("Ошибка в /analyze_service_pages")
        return {"error": str(e)}


@router.post("/analyze_with_templates", tags=["Анализ новых требований конкретного сервиса и их оформления"])
async def analyze_with_templates_route(payload: AnalyzeWithTemplatesRequest):
    try:
        result = analyze_with_templates(
            items=payload.items,
            prompt_template=payload.prompt_template,
            service_code=payload.service_code
        )
        return {"results": result}
    except Exception as e:
        logging.exception("Ошибка в /analyze_with_templates")
        return {"error": str(e)}
