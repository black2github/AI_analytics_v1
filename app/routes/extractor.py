# app/routes/extractor.py - ИСПРАВЛЕННАЯ ВЕРСИЯ с параллельной обработкой

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import logging
import anyio  # pip install anyio
import asyncio
from anyio import create_task_group, to_thread

from app.filter_all_fragments import filter_all_fragments
from app.filter_approved_fragments import filter_approved_fragments
# Импортируем функции из page_cache напрямую, т.к. они используют кеширование
from app.page_cache import get_page_data_cached
from app.filter_all_fragments import filter_all_fragments
from app.filter_approved_fragments import filter_approved_fragments

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


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ СИНХРОННЫЕ ФУНКЦИИ для выполнения в thread pool
# ============================================================================

def _process_page_all_content(page_id: str) -> PageContent:
    """
    Синхронная функция для извлечения ВСЕГО контента одной страницы.
    Будет выполняться в отдельном потоке через anyio.to_thread.run_sync
    """
    try:
        logger.debug("[_process_page_all_content] Processing page_id=%s", page_id)

        # Получаем данные страницы из кеша
        page_data = get_page_data_cached(page_id)

        if not page_data:
            logger.warning("[_process_page_all_content] No data found for page_id=%s", page_id)
            return PageContent(
                page_id=page_id,
                title=None,
                content=None,
                error="Page data not found"
            )

        title = page_data.get('title')
        html_content = page_data.get('raw_html')

        if not html_content:
            logger.warning("[_process_page_all_content] No content found for page_id=%s", page_id)
            return PageContent(
                page_id=page_id,
                title=title,
                content=None,
                error="Page content not found or empty"
            )

        # Извлекаем все фрагменты через filter_all_fragments
        extracted_content = filter_all_fragments(html_content)

        if not extracted_content or not extracted_content.strip():
            logger.warning("[_process_page_all_content] No extractable content for page_id=%s", page_id)
            return PageContent(
                page_id=page_id,
                title=title,
                content="",
                error="No extractable content found"
            )

        logger.debug("[_process_page_all_content] Successfully processed page_id=%s, content_length=%d",
                     page_id, len(extracted_content))

        return PageContent(
            page_id=page_id,
            title=title,
            content=extracted_content.strip()
        )

    except Exception as e:
        logger.error("[_process_page_all_content] Error processing page_id=%s: %s", page_id, str(e))
        return PageContent(
            page_id=page_id,
            title=None,
            content=None,
            error=f"Processing error: {str(e)}"
        )


def _process_page_approved_content(page_id: str) -> PageContent:
    """
    Синхронная функция для извлечения ПОДТВЕРЖДЕННОГО контента одной страницы.
    Будет выполняться в отдельном потоке через anyio.to_thread.run_sync
    """
    try:
        logger.debug("[_process_page_approved_content] Processing page_id=%s", page_id)

        # Получаем данные страницы из кеша
        page_data = get_page_data_cached(page_id)

        if not page_data:
            logger.warning("[_process_page_approved_content] No data found for page_id=%s", page_id)
            return PageContent(
                page_id=page_id,
                title=None,
                content=None,
                error="Page data not found"
            )

        title = page_data.get('title')
        html_content = page_data.get('raw_html')

        if not html_content:
            logger.warning("[_process_page_approved_content] No content found for page_id=%s", page_id)
            return PageContent(
                page_id=page_id,
                title=title,
                content=None,
                error="Page content not found or empty"
            )

        # Извлекаем только подтвержденные фрагменты через filter_approved_fragments
        extracted_content = filter_approved_fragments(html_content)

        if not extracted_content or not extracted_content.strip():
            logger.warning("[_process_page_approved_content] No approved content for page_id=%s", page_id)
            return PageContent(
                page_id=page_id,
                title=title,
                content="",
                error="No approved content found"
            )

        logger.debug("[_process_page_approved_content] Successfully processed page_id=%s, content_length=%d",
                     page_id, len(extracted_content))

        return PageContent(
            page_id=page_id,
            title=title,
            content=extracted_content.strip()
        )

    except Exception as e:
        logger.error("[_process_page_approved_content] Error processing page_id=%s: %s", page_id, str(e))
        return PageContent(
            page_id=page_id,
            title=None,
            content=None,
            error=f"Processing error: {str(e)}"
        )


# ============================================================================
# ЭНДПОИНТЫ с параллельной обработкой
# ============================================================================

@router.post("/extract_all_content",
             response_model=ExtractContentResponse,
             tags=["Извлечение контента"],
             summary="Получение полного текста требований со страниц Confluence")
async def extract_all_content(request: ExtractContentRequest):
    """
     ОПТИМИЗИРОВАНО: Извлекает полный текст требований с ПАРАЛЛЕЛЬНОЙ обработкой страниц.

    Возвращает все фрагменты текста, включая цветные (неподтвержденные) требования.
    Полезно для полного анализа всего содержимого страниц.

    Каждая страница обрабатывается в отдельном потоке, что позволяет:
    - Обрабатывать несколько страниц одновременно
    - Не блокировать event loop FastAPI
    - Обслуживать другие запросы параллельно

    Args:
        page_ids: Список идентификаторов страниц Confluence

    Returns:
        Список страниц с полным извлеченным текстом требований
    """
    logger.info("[extract_all_content] <- Processing %d page(s) in parallel", len(request.page_ids))

    if not request.page_ids:
        return ExtractContentResponse(
            success=False,
            total_pages=0,
            processed_pages=0,
            pages=[],
        )

    #  КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Параллельная обработка всех страниц
    async def process_page_async(page_id: str) -> PageContent:
        """Обертка для запуска синхронной функции в thread pool"""
        return await anyio.to_thread.run_sync(_process_page_all_content, page_id)

    # Запускаем обработку ВСЕХ страниц одновременно
    pages_content = await asyncio.gather(
        *[process_page_async(page_id) for page_id in request.page_ids]
    )

    # Подсчитываем успешно обработанные страницы
    processed_count = sum(1 for page in pages_content if page.content is not None)

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
     ОПТИМИЗИРОВАНО: Извлекает подтвержденный контент с ПАРАЛЛЕЛЬНОЙ обработкой страниц.

    Возвращает только фрагменты текста без цветового оформления (подтвержденные требования).
    Полезно для анализа стабильных, утвержденных требований.

    Каждая страница обрабатывается в отдельном потоке, что позволяет:
    - Обрабатывать несколько страниц одновременно
    - Не блокировать event loop FastAPI
    - Обслуживать другие запросы параллельно

    Args:
        page_ids: Список идентификаторов страниц Confluence

    Returns:
        Список страниц с извлеченным текстом подтвержденных требований
    """
    logger.info("[extract_approved_content] <- Processing %d page(s) in parallel", len(request.page_ids))

    if not request.page_ids:
        return ExtractContentResponse(
            success=False,
            total_pages=0,
            processed_pages=0,
            pages=[],
        )

    #  КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Параллельная обработка всех страниц
    async def process_page_async(page_id: str) -> PageContent:
        """Обертка для запуска синхронной функции в thread pool"""
        return await anyio.to_thread.run_sync(_process_page_approved_content, page_id)

    # Запускаем обработку ВСЕХ страниц одновременно
    pages_content = await asyncio.gather(
        *[process_page_async(page_id) for page_id in request.page_ids]
    )

    # Подсчитываем успешно обработанные страницы
    processed_count = sum(1 for page in pages_content if page.content is not None)

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
        "features": [
            "Parallel page processing with anyio",
            "Non-blocking I/O operations",
            "Thread pool execution for heavy tasks"
        ],
        "description": "Content extraction from Confluence pages using filter_all_fragments and filter_approved_fragments"
    }