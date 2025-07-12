# app/page_cache.py

import logging
from functools import lru_cache
from typing import Dict, Optional
import markdownify
from app.confluence_loader import confluence, extract_approved_fragments
from app.filter_all_fragments import filter_all_fragments
from app.services.template_type_analysis import analyze_content_template_type

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1000)
def get_page_data_cached(page_id: str) -> Optional[Dict]:
    """
    Кешированная функция для получения всех данных страницы за один запрос.

    Args:
        page_id: Идентификатор страницы

    Returns:
        Словарь с полными данными страницы или None при ошибке
    """
    logger.debug("[get_page_data_cached] <- page_id=%s", page_id)

    try:
        # Единственный запрос к Confluence API
        page = confluence.get_page_by_id(page_id, expand='body.storage,title')

        if not page:
            logger.warning("[get_page_data_cached] Page not found: %s", page_id)
            return None

        title = page.get('title', '')
        raw_html = page.get('body', {}).get('storage', {}).get('value', '')

        if not raw_html:
            logger.warning("[get_page_data_cached] No content found for page_id=%s", page_id)
            return None

        # Все виды обработки HTML выполняем один раз
        full_content = filter_all_fragments(raw_html)
        full_markdown = markdownify.markdownify(raw_html, heading_style="ATX")
        approved_content = extract_approved_fragments(raw_html)
        requirement_type = analyze_content_template_type(title, raw_html)

        result = {
            'id': page_id,
            'title': title,
            'raw_html': raw_html,
            'full_content': full_content,
            'full_markdown': full_markdown,
            'approved_content': approved_content,
            'requirement_type': requirement_type
        }

        logger.debug("[get_page_data_cached] -> Processed page: title='%s', type='%s'",
                     title, requirement_type)
        return result

    except Exception as e:
        logger.error("[get_page_data_cached] Error processing page_id=%s: %s", page_id, str(e))
        return None


def clear_page_cache():
    """Очистка кеша страниц"""
    get_page_data_cached.cache_clear()
    logger.info("[clear_page_cache] Page cache cleared")


def get_cache_info():
    """Информация о состоянии кеша"""
    cache_info = get_page_data_cached.cache_info()
    logger.info("[get_cache_info] Cache stats: hits=%d, misses=%d, size=%d",
                cache_info.hits, cache_info.misses, cache_info.currsize)
    return {
        'hits': cache_info.hits,
        'misses': cache_info.misses,
        'current_size': cache_info.currsize,
        'max_size': cache_info.maxsize
    }