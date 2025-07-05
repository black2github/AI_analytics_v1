# app/routes/template_analysis.py

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
import logging
from app.services.template_type_analysis import analyze_pages_template_types

logger = logging.getLogger(__name__)
router = APIRouter()


class AnalyzeTypesRequest(BaseModel):
    page_ids: List[str]


class AnalyzeTypesResponse(BaseModel):
    page_ids: List[str]
    template_types: List[Optional[str]]
    total_pages: int
    identified_types: int


@router.post("/analyze_types", response_model=AnalyzeTypesResponse, tags=["Анализ типов шаблонов"])
async def analyze_template_types(request: AnalyzeTypesRequest):
    """
    Определяет типы шаблонов требований для списка страниц Confluence

    Args:
        page_ids: Список идентификаторов страниц

    Returns:
        Список типов шаблонов для каждой страницы (или null если не определен)
    """
    logger.info("[analyze_template_types] <- Analyzing %d pages", len(request.page_ids))

    try:
        # Анализируем типы шаблонов
        template_types = analyze_pages_template_types(request.page_ids)

        # Подсчитываем статистику
        identified_count = sum(1 for t in template_types if t is not None)

        logger.info("[analyze_template_types] -> Identified %d/%d template types",
                    identified_count, len(request.page_ids))

        return AnalyzeTypesResponse(
            page_ids=request.page_ids,
            template_types=template_types,
            total_pages=len(request.page_ids),
            identified_types=identified_count
        )

    except Exception as e:
        logger.error("[analyze_template_types] Error: %s", str(e))
        return AnalyzeTypesResponse(
            page_ids=request.page_ids,
            template_types=[None] * len(request.page_ids),
            total_pages=len(request.page_ids),
            identified_types=0
        )