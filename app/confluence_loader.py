# app/confluence_loader.py

import logging
from copy import deepcopy
from types import NoneType
from typing import List, Dict, Optional
from atlassian import Confluence
from bs4 import BeautifulSoup, Tag
import markdownify
from app.config import CONFLUENCE_BASE_URL, CONFLUENCE_USER, CONFLUENCE_PASSWORD
from app.filter_all_fragments import filter_all_fragments
from app.filter_approved_fragments import filter_approved_fragments

if CONFLUENCE_BASE_URL is None:
    raise ValueError("Переменная окружения CONFLUENCE_BASE_URL не задана")

confluence = Confluence(
    url=CONFLUENCE_BASE_URL,
    username=CONFLUENCE_USER,
    password=CONFLUENCE_PASSWORD
)

try:
    from markdownify import markdownify as markdownify_fn
except ImportError:
    logging.error("[extract_approved_fragments] markdownify package not installed. Install it using 'pip install markdownify'")
    raise ImportError("markdownify package is required")

def extract_approved_fragments(html: str) -> str:
    """
    Извлекает только одобренные (чёрные) фрагменты текста, включая ссылки и таблицы,
    но только если они находятся внутри одобренных блоков.
    Фильтрация идёт по стилю родительского блока, не по вложенным тегам.
    Если родитель — цветной (нечёрный), всё внутри удаляется.
    """
    logging.debug("[extract_approved_fragments] <- html={%s}", html)
    return filter_approved_fragments(html)


from tenacity import retry, stop_after_attempt, wait_exponential
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_page_content_by_id(page_id: str, clean_html: bool = True) -> Optional[str]:
    """Получает содержимое страницы Confluence по её ID."""
    logging.info("[get_page_content_by_id] <- page_id=%s, clean_html=%s", page_id, clean_html)
    try:
        page = confluence.get_page_by_id(page_id, expand='body.storage')
        content = page.get('body', {}).get('storage', {}).get('value', '')
        if not content:
            logging.warning("[get_page_content_by_id] No content found for page_id=%s", page_id)
            return None

        if clean_html:
            # TODO: часть кода далее возвращает частичную кашу, без сохранения порядка, требуется исправление.
            # soup = BeautifulSoup(content, 'html.parser')
            # # Преобразуем таблицы в Markdown
            # for table in soup.find_all('table'):
            #     table_md = markdownify.markdownify(str(table), heading_style="ATX")
            #     # table_md = markdownify(str(table), heading_style="ATX")
            #     table.replace_with(table_md)
            # # Извлекаем текст, сохраняя содержимое всех тегов
            # text_parts = []
            # for element in soup.find_all(['p', 'li', 'span', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            #     text = element.get_text(separator=' ', strip=True)
            #     if text:
            #         text_parts.append(text)
            # # Добавляем Markdown-таблицы
            # for md_text in soup.find_all(text=True):
            #     if md_text.strip().startswith('|'):
            #         text_parts.append(md_text.strip())
            # content = '\n'.join(text_parts)

            content = confluence.get_page_by_id(page_id, expand='body.view')['body']['view']['value']
            content = filter_all_fragments(content)
            logging.debug("[get_page_content_by_id] Extracted text: %s", content[:200] + "...")

        logging.info("[get_page_content_by_id] -> Content length: %d characters: {%s}", len(content), content)
        return content
    except Exception as e:
        logging.error("[get_page_content_by_id] Error fetching page_id=%s: %s", page_id, str(e))
        return None


def get_page_title_by_id(page_id: str) -> Optional[str]:
    logging.debug("[get_page_title_by_id] <- page_id=%s", page_id)
    try:
        result = confluence.get_page_by_id(page_id, expand='title')
        logging.debug("[get_page_title_by_id] -> Result: %s", result)
        return result.get("title", "")
    except Exception as e:
        logging.warning("Ошибка при получении содержимого страницы {%s}: {%s}", page_id, e)
        return None


def load_pages_by_ids(page_ids: List[str]) -> List[Dict[str, str]]:
    """
    Загрузка страниц по идентификаторам и разбиение на идентификатор, заголовок, содержимое и подтвержденное содержимое
    (текст подтвержденных/черных требований).
    :param page_ids: список идентификаторов страниц для загрузки.
    :return:
    """
    logging.info("[load_pages_by_ids] <- page_ids={%s}", page_ids)
    pages = []
    for page_id in page_ids:
        title = get_page_title_by_id(page_id)
        raw_html = get_page_content_by_id(page_id, clean_html=False)
        full_md = markdownify.markdownify(raw_html, heading_style="ATX") if raw_html else None
        approved_md = extract_approved_fragments(raw_html) if raw_html else None

        if not (title and full_md and approved_md):
            logging.warning("Пропущена страница {%s} из-за ошибок загрузки.", page_id)
            continue

        pages.append({
            "id": page_id,
            "title": title,
            "content": full_md,
            "approved_content": approved_md
        })

    logging.info("[load_pages_by_ids] -> Успешно загружено страниц: %s из %s", len(pages), len(page_ids))
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

    def fetch_children(current_page_id: str):
        """Рекурсивно собирает идентификаторы дочерних страниц."""
        logging.debug("[fetch_children] <- current_page_id={%s}", current_page_id)
        try:
            # Получение дочерних страниц через Confluence API
            children = confluence.get_child_pages(current_page_id)
            for child in children:
                child_id = child["id"]
                child_page_ids.append(child_id)
                logging.debug("[get_child_page_ids] Found child page: %s for parent: %s", child_id, current_page_id)
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