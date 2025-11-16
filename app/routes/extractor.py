# app/routes/extractor.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import logging
from app.filter_all_fragments import filter_all_fragments
from app.filter_approved_fragments import filter_approved_fragments
from app.confluence_loader import get_page_content_by_id, get_page_title_by_id

logger = logging.getLogger(__name__)
router = APIRouter()


class ExtractContentRequest(BaseModel):
    """Запрос на извлечение контента страниц"""
    page_ids: List[str]


class PageContent(BaseModel):
    """Контент одной страницы"""
    page_id: str
    title: Optional[str] = None
    content: Optional[str] = None
    error: Optional[str] = None


class ExtractContentResponse(BaseModel):
    """Ответ с контентом страниц"""
    success: bool
    total_pages: int
    processed_pages: int
    pages: List[PageContent]


@router.post("/extract_all_content",
             response_model=ExtractContentResponse,
             tags=["Извлечение контента"],
             summary="Получение полного текста требований со страниц Confluence")
async def extract_all_content(request: ExtractContentRequest):
    """
    Извлекает полный текст требований со страниц Confluence через filter_all_fragments.

    Возвращает все фрагменты текста, включая цветные (неподтвержденные) требования.
    Полезно для полного анализа всего содержимого страниц.

    Args:
        page_ids: Список идентификаторов страниц Confluence

    Returns:
        Список страниц с полным извлеченным текстом требований
    """
    logger.info("[extract_all_content] <- Processing %d page(s)", len(request.page_ids))

    if not request.page_ids:
        return ExtractContentResponse(
            success=False,
            total_pages=0,
            processed_pages=0,
            pages=[],
        )

    pages_content = []
    processed_count = 0

    for page_id in request.page_ids:
        try:
            logger.debug("[extract_all_content] Processing page_id=%s", page_id)

            # Получаем заголовок страницы
            title = get_page_title_by_id(page_id)

            # Получаем HTML содержимое страницы
            html_content = get_page_content_by_id(page_id, clean_html=False)

            if not html_content:
                logger.warning("[extract_all_content] No content found for page_id=%s", page_id)
                pages_content.append(PageContent(
                    page_id=page_id,
                    title=title,
                    content=None,
                    error="Page content not found or empty"
                ))
                continue

            # Извлекаем все фрагменты через filter_all_fragments
            extracted_content = filter_all_fragments(html_content)

            if not extracted_content or not extracted_content.strip():
                logger.warning("[extract_all_content] No extractable content for page_id=%s", page_id)
                pages_content.append(PageContent(
                    page_id=page_id,
                    title=title,
                    content="",
                    error="No extractable content found"
                ))
                continue

            pages_content.append(PageContent(
                page_id=page_id,
                title=title,
                content=extracted_content.strip()
            ))
            processed_count += 1

            logger.debug("[extract_all_content] Successfully processed page_id=%s, content_length=%d",
                         page_id, len(extracted_content))

        except Exception as e:
            logger.error("[extract_all_content] Error processing page_id=%s: %s", page_id, str(e))
            pages_content.append(PageContent(
                page_id=page_id,
                title=None,
                content=None,
                error=f"Processing error: {str(e)}"
            ))

    logger.info("[extract_all_content] -> Processed %d/%d pages successfully",
                processed_count, len(request.page_ids))

    return ExtractContentResponse(
        success=processed_count > 0,
        total_pages=len(request.page_ids),
        processed_pages=processed_count,
        pages=pages_content
    )


@router.post("/extract_approved_content",
             response_model=ExtractContentResponse,
             tags=["Извлечение контента"],
             summary="Получение подтвержденных требований со страниц Confluence")
async def extract_approved_content(request: ExtractContentRequest):
    """
    Извлекает только подтвержденные (черные) требования со страниц Confluence через filter_approved_fragments.

    Возвращает только фрагменты текста без цветового оформления (подтвержденные требования).
    Полезно для анализа стабильных, утвержденных требований.

    Args:
        page_ids: Список идентификаторов страниц Confluence

    Returns:
        Список страниц с извлеченным текстом подтвержденных требований
    """
    logger.info("[extract_approved_content] <- Processing %d page(s)", len(request.page_ids))

    if not request.page_ids:
        return ExtractContentResponse(
            success=False,
            total_pages=0,
            processed_pages=0,
            pages=[],
        )

    pages_content = []
    processed_count = 0

    for page_id in request.page_ids:
        try:
            logger.debug("[extract_approved_content] Processing page_id=%s", page_id)

            # Получаем заголовок страницы
            title = get_page_title_by_id(page_id)

            # Получаем HTML содержимое страницы
            html_content = get_page_content_by_id(page_id, clean_html=False)

            if not html_content:
                logger.warning("[extract_approved_content] No content found for page_id=%s", page_id)
                pages_content.append(PageContent(
                    page_id=page_id,
                    title=title,
                    content=None,
                    error="Page content not found or empty"
                ))
                continue

            # Извлекаем только подтвержденные фрагменты через filter_approved_fragments
            extracted_content = filter_approved_fragments(html_content)

            if not extracted_content or not extracted_content.strip():
                logger.warning("[extract_approved_content] No approved content for page_id=%s", page_id)
                pages_content.append(PageContent(
                    page_id=page_id,
                    title=title,
                    content="",
                    error="No approved content found"
                ))
                continue

            pages_content.append(PageContent(
                page_id=page_id,
                title=title,
                content=extracted_content.strip()
            ))
            processed_count += 1

            logger.debug("[extract_approved_content] Successfully processed page_id=%s, content_length=%d",
                         page_id, len(extracted_content))

        except Exception as e:
            logger.error("[extract_approved_content] Error processing page_id=%s: %s", page_id, str(e))
            pages_content.append(PageContent(
                page_id=page_id,
                title=None,
                content=None,
                error=f"Processing error: {str(e)}"
            ))

    logger.info("[extract_approved_content] -> Processed %d/%d pages successfully",
                processed_count, len(request.page_ids))

    return ExtractContentResponse(
        success=processed_count > 0,
        total_pages=len(request.page_ids),
        processed_pages=processed_count,
        pages=pages_content
    )


@router.get("/extract_health", tags=["Извлечение контента"])
async def extract_health_check():
    """Проверка работоспособности модуля извлечения контента"""
    return {
        "status": "ok",
        "module": "content_extractor",
        "endpoints": [
            "POST /extract_all_content",
            "POST /extract_approved_content",
            "GET /extract_health"
        ],
        "description": "Content extraction from Confluence pages using filter_all_fragments and filter_approved_fragments"
    }