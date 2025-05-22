import os
import logging
from typing import List, Dict, Optional
from atlassian import Confluence
from app.config import CONFLUENCE_BASE_URL, CONFLUENCE_USER, CONFLUENCE_PASSWORD

# Настройка логгера
logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.INFO)
logging.basicConfig(level=logging.DEBUG)

print("password=")
print(CONFLUENCE_PASSWORD)

# Инициализация клиента Confluence
if CONFLUENCE_BASE_URL is None:
    raise ValueError("Переменная окружения CONFLUENCE_BASE_URL не задана")
confluence = Confluence(
    url=CONFLUENCE_BASE_URL,
    username=CONFLUENCE_USER,
    password=CONFLUENCE_PASSWORD
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
    с полями: id, title, content.
    """
    pages = []

    for page_id in page_ids:
        title = get_page_title_by_id(page_id)
        content = get_page_content_by_id(page_id)

        if title is None or content is None:
            logger.warning(f"Пропущена страница {page_id} из-за ошибок загрузки.")
            continue

        pages.append({
            "id": page_id,
            "title": title,
            "content": content
        })

    logger.info(f"Успешно загружено страниц: {len(pages)} из {len(page_ids)}")
    return pages
