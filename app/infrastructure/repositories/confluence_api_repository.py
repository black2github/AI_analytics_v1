# app/infrastructure/repositories/confluence_api_repository.py
import logging
from typing import List, Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential

from app.domain.repositories.confluence_repository import ConfluenceRepository
from app.confluence_loader import confluence
from app.filter_approved_fragments import filter_approved_fragments
from app.filter_all_fragments import filter_all_fragments
import markdownify

logger = logging.getLogger(__name__)


class ConfluenceApiRepository(ConfluenceRepository):
    """Реализация Confluence репозитория через API"""

    def __init__(self):
        self.confluence = confluence

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def get_page_content(self, page_id: str, include_storage: bool = True) -> Optional[Dict[str, Any]]:
        """Получение содержимого страницы"""
        logger.info("[get_page_content] <- page_id=%s, include_storage=%s", page_id, include_storage)

        try:
            expand_param = 'body.storage,title' if include_storage else 'title'
            page = self.confluence.get_page_by_id(page_id, expand=expand_param)

            if not page:
                logger.warning("[get_page_content] Page not found: %s", page_id)
                return None

            result = {
                "id": page_id,
                "title": page.get('title', ''),
                "raw_content": None,
                "full_content": None,
                "approved_content": None
            }

            if include_storage:
                raw_html = page.get('body', {}).get('storage', {}).get('value', '')
                if raw_html:
                    result["raw_content"] = raw_html
                    result["full_content"] = filter_all_fragments(raw_html)
                    result["approved_content"] = filter_approved_fragments(raw_html)

            logger.info("[get_page_content] -> Success, content length: %d",
                        len(result.get("full_content", "")))
            return result

        except Exception as e:
            logger.error("[get_page_content] Error fetching page %s: %s", page_id, str(e))
            return None

    async def get_page_title(self, page_id: str) -> Optional[str]:
        """Получение заголовка страницы"""
        logger.debug("[get_page_title] <- page_id=%s", page_id)

        try:
            page = self.confluence.get_page_by_id(page_id, expand='title')
            title = page.get("title", "") if page else None

            logger.debug("[get_page_title] -> title='%s'", title)
            return title

        except Exception as e:
            logger.error("[get_page_title] Error getting title for page %s: %s", page_id, str(e))
            return None

    async def get_child_pages(self, page_id: str) -> List[Dict[str, Any]]:
        """Получение дочерних страниц"""
        logger.info("[get_child_pages] <- page_id=%s", page_id)

        try:
            child_page_ids = []
            visited_pages = set()  # Защита от циклов

            def fetch_children_recursive(current_page_id: str):
                if current_page_id in visited_pages:
                    logger.warning("[get_child_pages] Circular reference detected for page_id=%s", current_page_id)
                    return

                visited_pages.add(current_page_id)

                try:
                    children = self.confluence.get_child_pages(current_page_id)
                    for child in children:
                        child_id = child["id"]
                        child_page_ids.append({
                            "id": child_id,
                            "title": child.get("title", ""),
                            "parent_id": current_page_id
                        })
                        logger.debug("[get_child_pages] Found child page: %s for parent: %s",
                                     child_id, current_page_id)
                        # Рекурсивный вызов для вложенных страниц
                        fetch_children_recursive(child_id)
                except Exception as e:
                    logger.error("[get_child_pages] Failed to fetch children for page %s: %s",
                                 current_page_id, str(e))

            fetch_children_recursive(page_id)

            logger.info("[get_child_pages] -> Found %d child pages", len(child_page_ids))
            return child_page_ids

        except Exception as e:
            logger.error("[get_child_pages] Error fetching child pages for %s: %s", page_id, str(e))
            return []

    async def load_pages_batch(self, page_ids: List[str]) -> List[Dict[str, Any]]:
        """Батчевая загрузка страниц"""
        logger.info("[load_pages_batch] <- Loading %d pages", len(page_ids))

        pages = []
        for page_id in page_ids:
            try:
                page_data = await self.get_page_content(page_id, include_storage=True)
                if page_data:
                    pages.append(page_data)
                else:
                    logger.warning("[load_pages_batch] Skipped page %s (not found or no content)", page_id)
            except Exception as e:
                logger.error("[load_pages_batch] Error loading page %s: %s", page_id, str(e))

        logger.info("[load_pages_batch] -> Successfully loaded %d out of %d pages",
                    len(pages), len(page_ids))
        return pages

    async def check_page_exists(self, page_id: str) -> bool:
        """Проверка существования страницы"""
        logger.debug("[check_page_exists] <- page_id=%s", page_id)

        try:
            page = self.confluence.get_page_by_id(page_id, expand='title')
            exists = page is not None

            logger.debug("[check_page_exists] -> exists=%s", exists)
            return exists

        except Exception as e:
            logger.error("[check_page_exists] Error checking page %s: %s", page_id, str(e))
            return False