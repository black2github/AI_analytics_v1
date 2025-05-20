import os
import logging
from typing import List, Dict, Optional
from atlassian import Confluence

# Настройка логгера
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Инициализация клиента Confluence
confluence = Confluence(
    url=os.environ.get("CONFLUENCE_BASE_URL"),
    username=os.environ.get("CONFLUENCE_USER"),
    password=os.environ.get("CONFLUENCE_API_TOKEN")
)


def get_page_content_by_id(page_id: str) -> Optional[str]:
    """
    Получает HTML-содержимое страницы Confluence по её ID.
    """
    try:
        result = confluence.get_page_by_id(page_id, expand='body.storage')
        return result.get("body", {}).get("storage", {}).get("value", "")
    except Exception as e:
        logger.warning(f"Ошибка при получении содержимого страницы {page_id}: {e}")
        return None


def get_page_title_by_id(page_id: str) -> Optional[str]:
    """
    Получает заголовок страницы Confluence по её ID.
    """
    try:
        result = confluence.get_page_by_id(page_id, expand='title')
        return result.get("title", "")
    except Exception as e:
        logger.warning(f"Ошибка при получении заголовка страницы {page_id}: {e}")
        return None


def load_pages_by_ids(page_ids: List[str]) -> List[Dict[str, str]]:
    """
    Загружает страницы по их идентификаторам и возвращает список словарей
    с полями: id, title, text.
    """
    pages = []

    for page_id in page_ids:
        title = get_page_title_by_id(page_id)
        text = get_page_content_by_id(page_id)

        if title is None or text is None:
            logger.warning(f"Пропущена страница {page_id} из-за ошибок загрузки.")
            continue

        pages.append({
            "id": page_id,
            "title": title,
            "text": text
        })

    logger.info(f"Успешно загружено страниц: {len(pages)} из {len(page_ids)}")
    return pages
