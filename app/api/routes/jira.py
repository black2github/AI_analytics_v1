# app/api/routes/jira.py
"""
Маршруты для работы с Jira API.
"""
import logging
from fastapi import APIRouter, Depends

from app.api.dto.jira_dto import JiraTaskRequest, JiraTaskResponse, JiraHealthResponse
from app.services.jira_service import JiraService, JiraServiceError
from app.infrastructure.di_container import get_jira_service  # Используем DI

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/analyze-jira-task",
             response_model=JiraTaskResponse,
             tags=["Анализ задач Jira"])
async def analyze_jira_task(
    request: JiraTaskRequest,
    jira_service: JiraService = Depends(get_jira_service)  # DI
):
    """
    Анализирует задачи Jira: извлекает идентификаторы страниц Confluence и проводит их анализ.

    Возвращает результат анализа в едином формате с HTTP 200.
    """
    logger.info("[analyze_jira_task] <- Request received with %d task IDs", len(request.jira_task_ids))

    try:
        result = await jira_service.analyze_jira_tasks(
            jira_task_ids=request.jira_task_ids,
            prompt_template=request.prompt_template,
            service_code=request.service_code
        )

        return JiraTaskResponse(**result)

    except JiraServiceError as e:
        logger.error("[analyze_jira_task] Jira service error: %s", str(e))
        return JiraTaskResponse(
            success=False,
            jira_task_ids=request.jira_task_ids,
            confluence_page_ids=[],
            total_pages_found=0,
            error=str(e)
        )
    except Exception as e:
        logger.error("[analyze_jira_task] Unexpected error: %s", str(e))
        return JiraTaskResponse(
            success=False,
            jira_task_ids=request.jira_task_ids,
            confluence_page_ids=[],
            total_pages_found=0,
            error=f"Internal server error: {str(e)}"
        )


@router.get("/jira/health",
            response_model=JiraHealthResponse,
            tags=["Проверка здоровья Jira модуля"])
async def health_check(
        jira_service: JiraService = Depends(get_jira_service)
):
    """Проверка доступности Jira модуля."""
    try:
        health_status = jira_service.get_health_status()
        return JiraHealthResponse(**health_status)
    except Exception as e:
        logger.error("[health_check] Error: %s", str(e))
        return JiraHealthResponse(
            success=False,
            message="Jira module health check failed",
            endpoints=[],
            error=f"Health check failed: {str(e)}"
        )