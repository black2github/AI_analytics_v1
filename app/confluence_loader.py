# app/confluence_loader.py

import logging
from typing import List, Dict, Optional
from atlassian import Confluence
from app.config import CONFLUENCE_BASE_URL, CONFLUENCE_USER, CONFLUENCE_PASSWORD
from app.filter_approved_fragments import filter_approved_fragments

if CONFLUENCE_BASE_URL is None:
    raise ValueError("Переменная окружения CONFLUENCE_BASE_URL не задана")

confluence = Confluence(
    url=CONFLUENCE_BASE_URL,
    username=CONFLUENCE_USER,
    password=CONFLUENCE_PASSWORD
)

logger = logging.getLogger(__name__)

try:
    from markdownify import markdownify as markdownify_fn
except ImportError:
    logging.error("[extract_approved_fragments] markdownify package not installed. Install it using 'pip install markdownify'")
    raise ImportError("markdownify package is required")

def extract_approved_fragments(html: str) -> str:
    """
    Извлекает только одобренные (чёрные) фрагменты текста, включая ссылки и таблицы.
    """
    logger.debug("[extract_approved_fragments] <- html={%s}", html)
    return filter_approved_fragments(html)


from tenacity import retry, stop_after_attempt, wait_exponential
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_page_content_by_id(page_id: str, clean_html: bool = True) -> Optional[str]:
    """
    Использует кеширование.
    Получает содержимое страницы Confluence по её ID.
    """
    logger.info("[get_page_content_by_id] <- page_id=%s, clean_html=%s", page_id, clean_html)

    # ДОБАВЛЯЕМ ИМПОРТ кешированной функции
    from app.page_cache import get_page_data_cached

    page_data = get_page_data_cached(page_id)
    if not page_data:
        logger.warning("[get_page_content_by_id] -> None.")
        return None

    if clean_html:
        content = page_data['full_content']
    else:
        content = page_data['raw_html']

    logger.info("[get_page_content_by_id] -> Content length %d characters", len(content))
    return content


def get_page_title_by_id(page_id: str) -> Optional[str]:
    """
    ОПТИМИЗИРОВАНО: Использует кеширование.
    Получает заголовок страницы по ID.
    """
    logger.debug("[get_page_title_by_id] <- page_id=%s", page_id)

    # ДОБАВЛЯЕМ ИМПОРТ кешированной функции
    from app.page_cache import get_page_data_cached

    page_data = get_page_data_cached(page_id)
    if not page_data:
        return None

    logger.debug("[get_page_title_by_id] -> Result: %s", page_data['title'])
    return page_data['title']


def load_pages_by_ids(page_ids: List[str]) -> List[Dict[str, str]]:
    """
    Загрузка страниц из Confluence по идентификаторам и разбиение на:
    идентификатор, заголовок, содержимое, подтвержденное содержимое и тип требования.
    ОПТИМИЗИРОВАНО: Использует кеширование для быстрой загрузки страниц.
    Args:
        page_ids: список идентификаторов страниц для загрузки.
    Returns:
        страницы (словари) с id, title, content, approved_content, requirement_type.
    """
    logger.info("[load_pages_by_ids] <- page_ids={%s}", page_ids)

    # ДОБАВЛЯЕМ ИМПОРТ кешированной функции
    from app.page_cache import get_page_data_cached

    pages = []
    for page_id in page_ids:
        # ЗАМЕНЯЕМ множественные запросы на один кешированный
        page_data = get_page_data_cached(page_id)

        if not page_data:
            logging.warning("Пропущена страница {%s} из-за ошибок загрузки.", page_id)
            continue

        # Проверяем наличие обязательных данных
        if not (page_data['title'] and page_data['full_markdown'] and page_data['approved_content']):
            logging.warning("Пропущена страница {%s} из-за отсутствия данных.", page_id)
            continue

        pages.append({
            "id": page_data['id'],
            "title": page_data['title'],
            "content": page_data['full_markdown'],
            "approved_content": page_data['approved_content'],
            "requirement_type": page_data['requirement_type']
        })

    logger.info("[load_pages_by_ids] -> Успешно загружено страниц: %s из %s", len(pages), len(page_ids))
    return pages


def load_template_markdown(page_id: str) -> Optional[str]:
    html = get_page_content_by_id(page_id, clean_html=False)
    if not html:
        return None
    return extract_approved_fragments(html)


def get_child_page_ids(page_id: str) -> List[str]:
    """Возвращает список идентификаторов всех дочерних страниц для указанной страницы Confluence.

    Args:
        page_id: Идентификатор страницы Confluence.

    Returns:
        Список идентификаторов дочерних страниц (включая вложенные).

    Raises:
        Exception: Если доступ к странице невозможен или произошла ошибка API.
    """
    child_page_ids = []
    visited_pages = set()  # ДОБАВЛЯЕМ защиту от циклов

    def fetch_children(current_page_id: str):
        """Рекурсивно собирает идентификаторы дочерних страниц."""
        # ДОБАВЛЯЕМ защиту от бесконечной рекурсии
        if current_page_id in visited_pages:
            logger.warning("[fetch_children] Circular reference detected for page_id=%s", current_page_id)
            return

        visited_pages.add(current_page_id)

        logger.debug("[fetch_children] <- current_page_id={%s}", current_page_id)
        try:
            # Получение дочерних страниц через Confluence API
            children = confluence.get_child_pages(current_page_id)
            for child in children:
                child_id = child["id"]
                child_page_ids.append(child_id)
                logger.debug("[get_child_page_ids] Found child page: %s for parent: %s", child_id, current_page_id)
                # Рекурсивный вызов для вложенных страниц
                fetch_children(child_id)
        except Exception as e:
            logging.error("Failed to fetch children for page %s: %s", current_page_id, str(e))
            raise

    try:
        fetch_children(page_id)
        return child_page_ids
    except Exception as e:
        logging.exception("Error fetching child pages for page_id=%s", page_id)
        raise