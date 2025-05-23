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
    soup = BeautifulSoup(html, "html.parser")
    fragments = []

    for el in soup.find_all(["p", "li", "span", "div"]):
        style = el.get("style", "").lower()
        has_link = el.find("a") is not None

        if has_link:
            fragments.append(str(el))
        elif ("color" not in style) or ("rgb(0,0,0)" in style) or ("#000000" in style):
            fragments.append(str(el))

    filtered_html = "\n".join(fragments)
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
