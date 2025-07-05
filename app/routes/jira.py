# app/routes/jira.py - ИСПРАВЛЕННАЯ ВЕРСИЯ с условным созданием объектов

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
    analysis: Union[Dict[str, Any], str]
    template_analysis: Optional[Dict[str, Any]] = None

    @field_validator('analysis')
    @classmethod
    def validate_analysis(cls, v):
        """Валидатор для поля analysis - приводим к нужному формату"""
        if isinstance(v, str):
            return {"error": v}
        elif isinstance(v, dict):
            return v
        else:
            return {"error": str(v)}


class JiraTaskRequest(BaseModel):
    """Модель запроса для анализа задач Jira."""
    jira_task_ids: List[str]
    prompt_template: Optional[str] = None
    service_code: Optional[str] = None
    check_templates: bool = False


class JiraTaskResponse(BaseModel):
    """Модель ответа с результатом анализа."""
    success: bool
    jira_task_ids: List[str]
    confluence_page_ids: List[str]
    total_pages_found: int
    analysis_results: Optional[List[PageAnalysisResult]] = None
    error: Optional[str] = None
    templates_analyzed: int = 0


@router.post("/analyze-jira-task", response_model=JiraTaskResponse, response_model_exclude_none=True)
async def analyze_jira_task(request: JiraTaskRequest):
    """
    Анализирует задачи Jira с опциональной проверкой соответствия шаблонам
    """
    logger.info("[analyze_jira_task] <- Request received with check_templates=%s", request.check_templates)

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
        logger.info("[analyze_jira_task] Starting analysis of %d pages with check_templates=%s",
                    len(page_ids), request.check_templates)

        analysis_results = analyze_pages(
            page_ids=page_ids,
            prompt_template=request.prompt_template,
            service_code=request.service_code,
            check_templates=request.check_templates
        )

        logger.info("[analyze_jira_task] -> Analysis completed successfully, got %d results", len(analysis_results))

        # ИСПРАВЛЕНО: Создаем объекты с условными параметрами
        parsed_results = []
        templates_analyzed = 0

        for result in analysis_results:
            try:
                template_analysis = result.get("template_analysis")

                # Подсчитываем количество проанализированных шаблонов
                if template_analysis and template_analysis.get("template_type"):
                    templates_analyzed += 1

                # ИСПРАВЛЕНИЕ: Используем ** для условной передачи параметров
                result_params = {
                    "page_id": result["page_id"],
                    "analysis": result["analysis"]
                }

                # Добавляем template_analysis только если он существует и не пустой
                if template_analysis:
                    result_params["template_analysis"] = template_analysis

                parsed_result = PageAnalysisResult(**result_params)
                parsed_results.append(parsed_result)

                logger.debug(
                    "[analyze_jira_task] Successfully processed result for page_id=%s, has_template_analysis=%s",
                    result["page_id"], template_analysis is not None)
            except Exception as e:
                logger.error("[analyze_jira_task] Error processing result for page_id=%s: %s",
                             result.get("page_id", "unknown"), str(e))
                # Создаем запасной результат без template_analysis
                parsed_results.append(PageAnalysisResult(
                    page_id=result.get("page_id", "unknown"),
                    analysis={"error": f"Processing error: {str(e)}"}
                ))

        logger.debug("[analyze_jira_task] Successfully parsed %d analysis results, %d templates analyzed",
                     len(parsed_results), templates_analyzed)

        response = JiraTaskResponse(
            success=True,
            jira_task_ids=jira_task_ids,
            confluence_page_ids=page_ids,
            total_pages_found=len(page_ids),
            analysis_results=parsed_results,
            templates_analyzed=templates_analyzed
        )

        return response

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
        ],
        "features": [
            "Confluence page extraction",
            "Requirements analysis",
            "Template structure analysis"
        ]
    }