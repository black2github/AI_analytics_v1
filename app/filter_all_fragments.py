# app/filter_all_fragments.py

import logging
from app.content_extractor import create_all_fragments_extractor

logger = logging.getLogger(__name__)


def filter_all_fragments(html: str) -> str:
    """
    Извлекает все фрагменты из HTML возвращая их с гибридной разметкой (Markdown + HTML)
    без учета цвета элементов
    """
    logger.info("[filter_all_fragments] <- {%s}", html[:200] + "...")

    extractor = create_all_fragments_extractor()
    result = extractor.extract(html)

    logger.info("[filter_all_fragments] -> {%s}", result)
    return result