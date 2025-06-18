# app/filter_approved_fragments.py

import logging
from app.content_extractor import create_approved_fragments_extractor

logger = logging.getLogger(__name__)


def filter_approved_fragments(html: str) -> str:
    """
    Извлекает подтвержденные фрагменты с гибридной разметкой (Markdown + HTML)
    """
    logger.info("[filter_approved_fragments] <- {%s}", html[:200] + "...")

    extractor = create_approved_fragments_extractor()
    result = extractor.extract(html)

    logger.info("[filter_approved_fragments] -> {%s}", result)
    return result