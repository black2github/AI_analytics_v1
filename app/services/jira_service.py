# app/services/jira_service.py
import logging
from typing import List, Dict, Any, Optional
from app.jira_loader import extract_confluence_page_ids_from_jira_tasks
from app.services.analysis_service import AnalysisService, AnalysisServiceError

logger = logging.getLogger(__name__)


class JiraServiceError(Exception):
    """Исключение для ошибок JiraService"""
    pass


class JiraService:
    """Сервис для работы с Jira и анализа связанных страниц Confluence"""

    def __init__(self):
        self.analysis_service = AnalysisService()

    async def analyze_jira_tasks(
            self,
            jira_task_ids: List[str],
            prompt_template: Optional[str] = None,
            service_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Анализирует задачи Jira: извлекает идентификаторы страниц Confluence и проводит их анализ.

        Returns:
            Словарь с результатами анализа в едином формате
        """
        logger.info("[analyze_jira_tasks] <- Processing %d Jira task IDs", len(jira_task_ids))

        try:
            if not jira_task_ids:
                return {
                    "success": False,
                    "jira_task_ids": [],
                    "confluence_page_ids": [],
                    "total_pages_found": 0,
                    "analysis_results": None,
                    "error": "jira_task_ids cannot be empty"
                }

            # Шаг 1: Извлекаем page_ids из задач Jira
            page_ids = extract_confluence_page_ids_from_jira_tasks(jira_task_ids)
            logger.info("[analyze_jira_tasks] Found %d Confluence page IDs", len(page_ids))

            if not page_ids:
                return {
                    "success": True,
                    "jira_task_ids": jira_task_ids,
                    "confluence_page_ids": [],
                    "total_pages_found": 0,
                    "analysis_results": None,
                    "error": "No Confluence page IDs found in the specified Jira tasks"
                }

            # Шаг 2: Проводим анализ найденных страниц
            logger.info("[analyze_jira_tasks] Starting analysis of %d pages", len(page_ids))

            try:
                analysis_results = await self.analysis_service.analyze_pages(
                    page_ids=page_ids,
                    prompt_template=prompt_template,
                    service_code=service_code
                )

                logger.info("[analyze_jira_tasks] -> Analysis completed successfully, got %d results",
                            len(analysis_results))

                return {
                    "success": True,
                    "jira_task_ids": jira_task_ids,
                    "confluence_page_ids": page_ids,
                    "total_pages_found": len(page_ids),
                    "analysis_results": analysis_results  # Уже в нужном формате
                }

            except AnalysisServiceError as e:
                logger.error("[analyze_jira_tasks] Analysis service error: %s", str(e))
                return {
                    "success": False,
                    "jira_task_ids": jira_task_ids,
                    "confluence_page_ids": page_ids,
                    "total_pages_found": len(page_ids),
                    "analysis_results": None,
                    "error": f"Analysis failed: {str(e)}"
                }

        except Exception as e:
            logger.error("[analyze_jira_tasks] Unexpected error: %s", str(e))
            return {
                "success": False,
                "jira_task_ids": jira_task_ids,
                "confluence_page_ids": [],
                "total_pages_found": 0,
                "analysis_results": None,
                "error": f"Internal server error: {str(e)}"
            }

    def get_health_status(self) -> Dict[str, Any]:
        """Возвращает статус здоровья Jira модуля"""
        return {
            "success": True,
            "message": "Jira module is healthy",
            "endpoints": [
                "POST /analyze-jira-task",
                "GET /jira/health"
            ]
        }