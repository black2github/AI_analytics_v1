# app/infrastructure/repositories/jira_api_repository.py
import logging
from typing import List, Optional, Dict, Any

from app.domain.repositories.jira_repository import JiraRepository
from app.jira_loader import (
    get_jira_task_description_via_session,
    extract_confluence_page_ids_from_jira_tasks,
    _extract_confluence_page_ids_from_html
)

logger = logging.getLogger(__name__)


class JiraApiRepository(JiraRepository):
    """Реализация Jira репозитория через API"""

    async def get_task_description(self, task_id: str) -> Optional[str]:
        """Получение описания задачи"""
        logger.info("[get_task_description] <- task_id=%s", task_id)

        try:
            description = get_jira_task_description_via_session(task_id)

            if description:
                logger.info("[get_task_description] -> Success, description length: %d", len(description))
            else:
                logger.warning("[get_task_description] -> No description found for task %s", task_id)

            return description

        except Exception as e:
            logger.error("[get_task_description] Error getting description for task %s: %s", task_id, str(e))
            return None

    async def extract_confluence_links(self, task_ids: List[str]) -> List[str]:
        """Извлечение ссылок на Confluence из задач"""
        logger.info("[extract_confluence_links] <- Processing %d task IDs", len(task_ids))

        try:
            page_ids = extract_confluence_page_ids_from_jira_tasks(task_ids)

            logger.info("[extract_confluence_links] -> Found %d unique Confluence page IDs", len(page_ids))
            return page_ids

        except Exception as e:
            logger.error("[extract_confluence_links] Error extracting links from tasks %s: %s", task_ids, str(e))
            return []

    async def check_task_exists(self, task_id: str) -> bool:
        """Проверка существования задачи"""
        logger.debug("[check_task_exists] <- task_id=%s", task_id)

        try:
            description = await self.get_task_description(task_id)
            exists = description is not None

            logger.debug("[check_task_exists] -> exists=%s", exists)
            return exists

        except Exception as e:
            logger.error("[check_task_exists] Error checking task %s: %s", task_id, str(e))
            return False

    async def get_task_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Получение информации о задаче"""
        logger.info("[get_task_info] <- task_id=%s", task_id)

        try:
            description = await self.get_task_description(task_id)

            if not description:
                return None

            # Извлекаем дополнительную информацию
            confluence_page_ids = _extract_confluence_page_ids_from_html(description)

            task_info = {
                "task_id": task_id,
                "description": description,
                "description_length": len(description),
                "confluence_page_ids": confluence_page_ids,
                "confluence_pages_count": len(confluence_page_ids)
            }

            logger.info("[get_task_info] -> Success, found %d Confluence links", len(confluence_page_ids))
            return task_info

        except Exception as e:
            logger.error("[get_task_info] Error getting info for task %s: %s", task_id, str(e))
            return None