import os
import logging
from typing import List, Dict, Optional
from atlassian import Confluence
from bs4 import BeautifulSoup
import markdownify

from app.config import CONFLUENCE_BASE_URL, CONFLUENCE_USER, CONFLUENCE_PASSWORD

# Настройка логгера
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

# Инициализация клиента Confluence
if CONFLUENCE_BASE_URL is None:
    raise ValueError("Переменная окружения CONFLUENCE_BASE_URL не задана")
confluence = Confluence(
    url=CONFLUENCE_BASE_URL,
    username=CONFLUENCE_USER,
    password=CONFLUENCE_PASSWORD
)


def get_page_content_by_id(page_id: str, clean_html: bool = True) -> Optional[str]:
    """
    Получает содержимое страницы Confluence по её ID.
    Если clean_html=True, преобразует HTML в чистый текст с Markdown-таблицами.
    """
    try:
        result = confluence.get_page_by_id(page_id, expand='body.storage')
        html = result.get("body", {}).get("storage", {}).get("value", "")

        if clean_html:
            soup = BeautifulSoup(html, "html.parser")

            # Преобразуем таблицы и оставшийся HTML в markdown
            markdown_text = markdownify.markdownify(str(soup), heading_style="ATX")
            return markdown_text.strip()

        return html
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
        content = get_page_content_by_id(page_id, clean_html=True)

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
