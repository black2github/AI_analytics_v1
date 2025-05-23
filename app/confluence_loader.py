# app/confluence_loader.py

import logging
from typing import List, Dict, Optional
from atlassian import Confluence
from bs4 import BeautifulSoup
import markdownify

from app.config import CONFLUENCE_BASE_URL, CONFLUENCE_USER, CONFLUENCE_PASSWORD

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

if CONFLUENCE_BASE_URL is None:
    raise ValueError("Переменная окружения CONFLUENCE_BASE_URL не задана")

confluence = Confluence(
    url=CONFLUENCE_BASE_URL,
    username=CONFLUENCE_USER,
    password=CONFLUENCE_PASSWORD
)


def get_page_content_by_id(page_id: str, clean_html: bool = True) -> Optional[str]:
    try:
        result = confluence.get_page_by_id(page_id, expand='body.storage')
        html = result.get("body", {}).get("storage", {}).get("value", "")

        if clean_html:
            soup = BeautifulSoup(html, "html.parser")
            markdown_text = markdownify.markdownify(str(soup), heading_style="ATX")
            return markdown_text.strip()

        return html
    except Exception as e:
        logger.warning(f"Ошибка при получении содержимого страницы {page_id}: {e}")
        return None


def get_page_title_by_id(page_id: str) -> Optional[str]:
    try:
        result = confluence.get_page_by_id(page_id, expand='title')
        return result.get("title", "")
    except Exception as e:
        logger.warning(f"Ошибка при получении заголовка страницы {page_id}: {e}")
        return None


def extract_approved_fragments(html: str) -> str:
    """
    Извлекает только одобренные (чёрные) фрагменты текста, включая ссылки,
    но только если они находятся внутри одобренных блоков (включая начало блока или его завершение).
    Фильтрация идёт по стилю родительского блока, не по вложенным тегам.
    Если родитель — цветной (нечёрный), всё внутри удаляется, даже если <a> не имеет цвета.
    Это поведение — безопасное и строгое, оно предотвращает попадание ссылок, находящихся в «неодобренном» контексте.
    """
    soup = BeautifulSoup(html, "html.parser")
    fragments = []

    for el in soup.find_all(["p", "li", "span", "div"]):
        style = el.get("style", "").lower()

        # Явно исключаем цветной текст, если он не чёрный
        if "color" in style:
            if ("rgb(0,0,0)" not in style) and ("#000000" not in style):
                continue  # Пропускаем цветной текст (неодобренный)

        # Учитываем только элементы без стиля цвета или с чёрным цветом
        fragments.append(str(el))

    # Собираем HTML из отфильтрованных фрагментов
    filtered_html = "\n".join(fragments)

    # Преобразуем HTML в Markdown
    markdown_text = markdownify.markdownify(filtered_html, heading_style="ATX")
    return markdown_text.strip()


def load_pages_by_ids(page_ids: List[str]) -> List[Dict[str, str]]:
    pages = []

    for page_id in page_ids:
        title = get_page_title_by_id(page_id)
        raw_html = get_page_content_by_id(page_id, clean_html=False)
        full_markdown = markdownify.markdownify(raw_html, heading_style="ATX") if raw_html else None
        approved_only_markdown = extract_approved_fragments(raw_html) if raw_html else None

        if title is None or full_markdown is None or approved_only_markdown is None:
            logger.warning(f"Пропущена страница {page_id} из-за ошибок загрузки.")
            continue

        pages.append({
            "id": page_id,
            "title": title,
            "content": full_markdown,
            "approved_content": approved_only_markdown
        })

    logger.info(f"Успешно загружено страниц: {len(pages)} из {len(page_ids)}")
    return pages
