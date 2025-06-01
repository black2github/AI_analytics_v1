# app/confluence_loader.py

import logging
from typing import List, Dict, Optional
from atlassian import Confluence
from bs4 import BeautifulSoup
import markdownify
from app.config import CONFLUENCE_BASE_URL, CONFLUENCE_USER, CONFLUENCE_PASSWORD

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
        logging.warning("Ошибка при получении содержимого страницы {%s}: {%s}", page_id, e)
        return None


def get_page_title_by_id(page_id: str) -> Optional[str]:
    try:
        result = confluence.get_page_by_id(page_id, expand='title')
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