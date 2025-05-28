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
        if "color" in style and ("rgb(0,0,0)" not in style and "#000000" not in style):
            continue # Пропускаем цветной текст (неодобренный)

        # Учитываем только элементы без стиля цвета или с чёрным цветом
        fragments.append(str(el))

    markdown_text = markdownify.markdownify("\n".join(fragments), heading_style="ATX")
    return markdown_text.strip()


def get_page_content_by_id(page_id: str, clean_html: bool = True) -> Optional[str]:
    try:
        result = confluence.get_page_by_id(page_id, expand='body.storage')
        html = result.get("body", {}).get("storage", {}).get("value", "")
        if clean_html:
            return markdownify.markdownify(html, heading_style="ATX").strip()
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


def load_pages_by_ids(page_ids: List[str]) -> List[Dict[str, str]]:
    pages = []
    for page_id in page_ids:
        title = get_page_title_by_id(page_id)
        raw_html = get_page_content_by_id(page_id, clean_html=False)
        full_md = markdownify.markdownify(raw_html, heading_style="ATX") if raw_html else None
        approved_md = extract_approved_fragments(raw_html) if raw_html else None

        if not (title and full_md and approved_md):
            logger.warning(f"Пропущена страница {page_id} из-за ошибок загрузки.")
            continue

        pages.append({
            "id": page_id,
            "title": title,
            "content": full_md,
            "approved_content": approved_md
        })

    logger.info(f"Успешно загружено страниц: {len(pages)} из {len(page_ids)}")
    return pages


def load_template_markdown(page_id: str) -> Optional[str]:
    html = get_page_content_by_id(page_id, clean_html=False)
    if not html:
        return None
    return extract_approved_fragments(html)