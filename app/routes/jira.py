# app/routes/jira.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
"""
Маршруты для работы с Jira API.
"""
import logging
from typing import List, Optional, Dict, Any, Union
from fastapi import APIRouter
from pydantic import BaseModel, field_validator
from app.jira_loader import extract_confluence_page_ids_from_jira_tasks
from app.services.analysis_service import analyze_pages

# Создаем APIRouter для FastAPI
router = APIRouter()

logger = logging.getLogger(__name__)


class PageAnalysisResult(BaseModel):
    """Модель результата анализа одной страницы."""
    page_id: str
    analysis: Union[Dict[str, Any], str]  # ИСПРАВЛЕНИЕ: Может быть и словарем, и строкой

    @field_validator('analysis')
    @classmethod
    def validate_analysis(cls, v):
        """Валидатор для поля analysis - приводим к нужному формату"""
        if isinstance(v, str):
            # Если строка - оборачиваем в словарь для единообразия
            return {"error": v}
        elif isinstance(v, dict):
            return v
        else:
            # Неожиданный тип - преобразуем в строку и оборачиваем
            return {"error": str(v)}


class JiraTaskRequest(BaseModel):
    """Модель запроса для анализа задач Jira."""
    jira_task_ids: List[str]
    prompt_template: Optional[str] = None
    service_code: Optional[str] = None


class JiraTaskResponse(BaseModel):
    """Модель ответа с результатом анализа."""
    success: bool
    jira_task_ids: List[str]
    confluence_page_ids: List[str]
    total_pages_found: int
    analysis_results: Optional[List[PageAnalysisResult]] = None
    error: Optional[str] = None


@router.post("/analyze-jira-task", response_model=JiraTaskResponse)
async def analyze_jira_task(request: JiraTaskRequest):
    """
    Анализирует задачи Jira: извлекает идентификаторы страниц Confluence и проводит их анализ.

    Ожидает JSON с массивом jira_task_ids и опциональными параметрами:
    {
        "jira_task_ids": ["GBO-123", "GBO-456"],
        "prompt_template": "optional_prompt_template",
        "service_code": "optional_service_code"
    }

    Возвращает:
    {
        "success": true,
        "jira_task_ids": ["GBO-123", "GBO-456"],
        "confluence_page_ids": ["123456", "789012"],
        "total_pages_found": 2,
        "analysis_results": [
            {
                "page_id": "123456",
                "analysis": {
                    "Общие требования к ЭФ": {
                        "Полнота и непротиворечивость": "...",
                        "Корректность алгоритмов и процедур": "..."
                    }
                }
            }
        ]
    }
    """
    logger.info("[analyze_jira_task] <- Request received")

    try:
        jira_task_ids = request.jira_task_ids

        if not jira_task_ids:
            return JiraTaskResponse(
                success=False,
                jira_task_ids=[],
                confluence_page_ids=[],
                total_pages_found=0,
                error="jira_task_ids cannot be empty"
            )

        logger.info("[analyze_jira_task] Processing %d Jira task IDs", len(jira_task_ids))

        # Шаг 1: Извлекаем page_ids из задач Jira
        page_ids = extract_confluence_page_ids_from_jira_tasks(jira_task_ids)

        logger.info("[analyze_jira_task] Found %d Confluence page IDs", len(page_ids))

        if not page_ids:
            return JiraTaskResponse(
                success=True,
                jira_task_ids=jira_task_ids,
                confluence_page_ids=[],
                total_pages_found=0,
                analysis_results=None,
                error="No Confluence page IDs found in the specified Jira tasks"
            )

        # Шаг 2: Проводим анализ найденных страниц
        logger.info("[analyze_jira_task] Starting analysis of %d pages", len(page_ids))

        analysis_results = analyze_pages(
            page_ids=page_ids,
            prompt_template=request.prompt_template,
            service_code=request.service_code
        )

        logger.info("[analyze_jira_task] -> Analysis completed successfully, got %d results", len(analysis_results))

        # ИСПРАВЛЕНИЕ: Безопасное преобразование результатов
        parsed_results = []
        for result in analysis_results:
            try:
                # result имеет структуру: {"page_id": "123", "analysis": {...} или "строка"}
                parsed_result = PageAnalysisResult(
                    page_id=result["page_id"],
                    analysis=result["analysis"]  # Валидатор обработает тип
                )
                parsed_results.append(parsed_result)
                logger.debug("[analyze_jira_task] Successfully processed result for page_id=%s", result["page_id"])
            except Exception as e:
                logger.error("[analyze_jira_task] Error processing result for page_id=%s: %s",
                           result.get("page_id", "unknown"), str(e))
                # Создаем запасной результат
                parsed_results.append(PageAnalysisResult(
                    page_id=result.get("page_id", "unknown"),
                    analysis={"error": f"Processing error: {str(e)}"}
                ))

        logger.debug("[analyze_jira_task] Successfully parsed %d analysis results", len(parsed_results))

        return JiraTaskResponse(
            success=True,
            jira_task_ids=jira_task_ids,
            confluence_page_ids=page_ids,
            total_pages_found=len(page_ids),
            analysis_results=parsed_results
        )

    except Exception as e:
        logger.error("[analyze_jira_task] Error: %s", str(e))
        return JiraTaskResponse(
            success=False,
            jira_task_ids=request.jira_task_ids if request else [],
            confluence_page_ids=[],
            total_pages_found=0,
            error=str(e)
        )


@router.get("/jira/health")
async def health_check():
    """Проверка доступности Jira модуля."""
    return {
        "success": True,
        "message": "Jira module is healthy",
        "endpoints": [
            "POST /analyze-jira-task",
            "GET /jira/health"
        ]
    }