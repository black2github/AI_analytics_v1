# app/api/routes/analyze.py
import logging
from fastapi import APIRouter, Depends
from typing import List

from app.api.dto.analyze_dto import (
    AnalyzeTextRequest, AnalyzeTextResponse,
    AnalyzePagesRequest, AnalyzePagesResponse, PageAnalysisResult,
    AnalyzeWithTemplatesRequest, AnalyzeWithTemplatesResponse, TemplateAnalysisResult,
    AnalyzeServicePagesRequest
)
from app.services.analysis_service import AnalysisService, AnalysisServiceError
from app.infrastructure.di_container import get_analysis_service  # Используем DI
from app.service_registry import is_valid_service

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/analyze",
             response_model=AnalyzeTextResponse,
             tags=["Анализ текстовых требований сервиса"])
async def analyze_from_text(
    request: AnalyzeTextRequest,
    analysis_service: AnalysisService = Depends(get_analysis_service)  # DI
):
    """Анализирует текстовые требования"""
    logger.info("[analyze_from_text] <- %s", request)

    try:
        result = await analysis_service.analyze_text(
            text=request.text,
            prompt_template=request.prompt_template,
            service_code=request.service_code
        )

        return AnalyzeTextResponse(result=result)

    except AnalysisServiceError as e:
        logger.error("[analyze_from_text] Analysis error: %s", str(e))
        return AnalyzeTextResponse(error=str(e))
    except Exception as e:
        logger.error("[analyze_from_text] Unexpected error: %s", str(e))
        return AnalyzeTextResponse(error=f"Internal server error: {str(e)}")


@router.post("/analyze_pages",
             response_model=AnalyzePagesResponse,
             tags=["Анализ существующих (ранее) требований сервиса"])
async def analyze_service_pages(
        request: AnalyzePagesRequest,
        analysis_service: AnalysisService = Depends(get_analysis_service)
):
    """Анализирует страницы Confluence"""
    logger.info("[analyze_service_pages] <- %s", request)

    try:
        results = await analysis_service.analyze_pages(
            page_ids=request.page_ids,
            prompt_template=request.prompt_template,
            service_code=request.service_code
        )

        # Конвертируем в DTO
        page_results = [
            PageAnalysisResult(page_id=result["page_id"], analysis=result["analysis"])
            for result in results
        ]

        return AnalyzePagesResponse(results=page_results)

    except AnalysisServiceError as e:
        logger.error("[analyze_service_pages] Analysis error: %s", str(e))
        return AnalyzePagesResponse(error=str(e))
    except Exception as e:
        logger.error("[analyze_service_pages] Unexpected error: %s", str(e))
        return AnalyzePagesResponse(error=f"Internal server error: {str(e)}")


@router.post("/analyze_service_pages/{code}",
             response_model=AnalyzePagesResponse,
             tags=["Анализ существующих (ранее) требований конкретного сервиса"])
async def analyze_service_pages_by_code(
        code: str,
        request: AnalyzeServicePagesRequest,
        analysis_service: AnalysisService = Depends(get_analysis_service)
):
    """Анализирует страницы конкретного сервиса"""
    logger.info("[analyze_service_pages_by_code] <- code=%s, %s", code, request)

    if not is_valid_service(code):
        return AnalyzePagesResponse(error=f"Сервис с кодом {code} не найден")

    try:
        results = await analysis_service.analyze_pages(
            page_ids=request.page_ids,
            prompt_template=request.prompt_template,
            service_code=code
        )

        # Конвертируем в DTO
        page_results = [
            PageAnalysisResult(page_id=result["page_id"], analysis=result["analysis"])
            for result in results
        ]

        logger.info("[analyze_service_pages_by_code] -> result count=%d", len(page_results))
        return AnalyzePagesResponse(results=page_results)

    except AnalysisServiceError as e:
        logger.error("[analyze_service_pages_by_code] Analysis error: %s", str(e))
        return AnalyzePagesResponse(error=str(e))
    except Exception as e:
        logger.error("[analyze_service_pages_by_code] Unexpected error: %s", str(e))
        return AnalyzePagesResponse(error=f"Internal server error: {str(e)}")


@router.post("/analyze_with_templates",
             response_model=AnalyzeWithTemplatesResponse,
             tags=["Анализ новых требований сервиса и их оформления"])
async def analyze_with_templates_route(
        request: AnalyzeWithTemplatesRequest,
        analysis_service: AnalysisService = Depends(get_analysis_service)
):
    """Анализирует новые требования на соответствие шаблонам с передачей шаблона в LLM"""
    logger.info("[analyze_with_templates_route] <- %s", request)

    try:
        results = await analysis_service.analyze_with_templates(
            items=request.items,
            prompt_template=request.prompt_template,
            service_code=request.service_code
        )

        # Конвертируем в DTO
        template_results = [
            TemplateAnalysisResult(
                page_id=result["page_id"],
                requirement_type=result["requirement_type"],
                template_analysis=result["template_analysis"],
                legacy_formatting_issues=result["legacy_formatting_issues"],
                template_used=result.get("template_used"),
                analysis_timestamp=result.get("analysis_timestamp"),
                storage_used=result.get("storage_used")
            )
            for result in results
        ]

        logger.info("[analyze_with_templates_route] -> result count=%d", len(template_results))
        return AnalyzeWithTemplatesResponse(results=template_results)

    except AnalysisServiceError as e:
        logger.error("[analyze_with_templates_route] Analysis error: %s", str(e))
        return AnalyzeWithTemplatesResponse(error=str(e))
    except Exception as e:
        logger.error("[analyze_with_templates_route] Unexpected error: %s", str(e))
        return AnalyzeWithTemplatesResponse(error=f"Internal server error: {str(e)}")