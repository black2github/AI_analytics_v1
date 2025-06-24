# app/api/routes/loader.py - обновляем dependencies
import logging
from fastapi import APIRouter, Depends
from typing import List, Optional

from app.api.dto.loader_dto import (
    LoadPagesRequest, LoadPagesResponse, LoadTemplatesRequest, LoadTemplatesResponse,
    RemovePagesRequest, RemovePagesResponse, ChildPagesResponse, DebugResponse
)
from app.services.document_service import DocumentService, DocumentServiceError
from app.infrastructure.di_container import get_document_service  # Используем DI
from app.config import UNIFIED_STORAGE_NAME

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/load_pages",
             response_model=LoadPagesResponse,
             tags=["Загрузка Confluence страниц требований"])
async def load_service_pages(
    request: LoadPagesRequest,
    document_service: DocumentService = Depends(get_document_service)  # DI
):
    """Загружает ТОЛЬКО подтвержденные требования в единое хранилище."""
    logger.info("[load_service_pages] <- %s", request)

    try:
        result = await document_service.load_and_index_pages(
            page_ids=request.page_ids,
            service_code=request.service_code,
            source=request.source
        )

        if result.success:
            return LoadPagesResponse(
                success=True,
                message=result.message,
                total_pages=result.total_pages,
                pages_with_approved_content=result.pages_with_approved_content,
                documents_created=result.documents_created,
                is_platform=result.is_platform,
                storage=result.storage
            )
        else:
            return LoadPagesResponse(
                success=False,
                storage=result.storage,
                error=result.error or result.message
            )

    except DocumentServiceError as e:
        logger.error("[load_service_pages] Business error: %s", str(e))
        return LoadPagesResponse(
            success=False,
            storage=UNIFIED_STORAGE_NAME,
            error=str(e)
        )
    except Exception as e:
        logger.error("[load_service_pages] Unexpected error: %s", str(e))
        return LoadPagesResponse(
            success=False,
            storage=UNIFIED_STORAGE_NAME,
            error=f"Internal server error: {str(e)}"
        )


@router.post("/load_templates",
             response_model=LoadTemplatesResponse,
             tags=["Загрузка Confluence шаблонов страниц требований"])
async def load_templates(
        request: LoadTemplatesRequest,
        document_service: DocumentService = Depends(get_document_service)
):
    """Загружает шаблоны требований в единое хранилище."""
    logger.info("[load_templates] <- %s", request)

    try:
        templates_loaded = await document_service.load_templates(request.templates)

        return LoadTemplatesResponse(
            message=f"Templates loaded: {templates_loaded}",
            templates_loaded=templates_loaded,
            storage=UNIFIED_STORAGE_NAME
        )

    except DocumentServiceError as e:
        logger.error("[load_templates] Business error: %s", str(e))
        return LoadTemplatesResponse(
            storage=UNIFIED_STORAGE_NAME,
            error=str(e)
        )
    except Exception as e:
        logger.error("[load_templates] Unexpected error: %s", str(e))
        return LoadTemplatesResponse(
            storage=UNIFIED_STORAGE_NAME,
            error=f"Internal server error: {str(e)}"
        )


@router.get("/child_pages/{page_id}",
            response_model=ChildPagesResponse,
            tags=["Получение дочерних страниц Confluence и их опциональная загрузка в хранилище"])
async def get_child_pages(
        page_id: str,
        service_code: Optional[str] = None,
        source: str = "DBOCORPESPLN",
        document_service: DocumentService = Depends(get_document_service)
):
    """Возвращает список идентификаторов дочерних страниц и загружает их при указании service_code."""
    logger.info("[get_child_pages] <- page_id=%s, service_code=%s, source=%s",
                page_id, service_code, source)

    try:
        result = await document_service.get_child_pages(page_id, service_code, source)

        load_result_response = None
        if result.load_result:
            if result.load_result.success:
                load_result_response = LoadPagesResponse(
                    success=True,
                    message=result.load_result.message,
                    total_pages=result.load_result.total_pages,
                    pages_with_approved_content=result.load_result.pages_with_approved_content,
                    documents_created=result.load_result.documents_created,
                    is_platform=result.load_result.is_platform,
                    storage=result.load_result.storage
                )
            else:
                load_result_response = LoadPagesResponse(
                    success=False,
                    storage=result.load_result.storage,
                    error=result.load_result.error
                )

        return ChildPagesResponse(
            page_ids=result.page_ids,
            load_result=load_result_response,
            storage=UNIFIED_STORAGE_NAME
        )

    except DocumentServiceError as e:
        logger.error("[get_child_pages] Business error: %s", str(e))
        return ChildPagesResponse(
            page_ids=[],
            storage=UNIFIED_STORAGE_NAME,
            error=str(e)
        )
    except Exception as e:
        logger.error("[get_child_pages] Unexpected error: %s", str(e))
        return ChildPagesResponse(
            page_ids=[],
            storage=UNIFIED_STORAGE_NAME,
            error=f"Internal server error: {str(e)}"
        )


@router.post("/remove_service_pages",
             response_model=RemovePagesResponse,
             tags=["Удаление фрагментов страниц из единого хранилища"])
async def remove_service_pages(
        request: RemovePagesRequest,
        document_service: DocumentService = Depends(get_document_service)
):
    """Удаляет фрагменты указанных страниц из единого хранилища."""
    logger.info("[remove_service_pages] <- %s", request)

    try:
        result = await document_service.remove_page_fragments(request.page_ids)

        if result.success:
            return RemovePagesResponse(
                status="success",
                deleted_count=result.deleted_count,
                page_ids=result.page_ids,
                storage=result.storage
            )
        else:
            return RemovePagesResponse(
                status="error",
                page_ids=result.page_ids,
                storage=result.storage,
                error=result.error
            )

    except Exception as e:
        logger.error("[remove_service_pages] Unexpected error: %s", str(e))
        return RemovePagesResponse(
            status="error",
            page_ids=request.page_ids,
            storage=UNIFIED_STORAGE_NAME,
            error=f"Internal server error: {str(e)}"
        )


@router.post("/remove_platform_pages",
             response_model=RemovePagesResponse,
             tags=["Удаление фрагментов платформенных страниц"])
async def remove_platform_pages(
        request: RemovePagesRequest,
        document_service: DocumentService = Depends(get_document_service)
):
    """Удаляет фрагменты платформенных страниц из единого хранилища."""
    logger.info("[remove_platform_pages] <- %s", request)

    if not request.service_code:
        return RemovePagesResponse(
            status="error",
            page_ids=request.page_ids,
            storage=UNIFIED_STORAGE_NAME,
            error="service_code is required for platform pages"
        )

    try:
        result = await document_service.remove_platform_fragments(
            request.page_ids,
            request.service_code
        )

        if result.success:
            return RemovePagesResponse(
                status="success",
                deleted_count=result.deleted_count,
                page_ids=result.page_ids,
                storage=result.storage
            )
        else:
            return RemovePagesResponse(
                status="error",
                page_ids=result.page_ids,
                storage=result.storage,
                error=result.error
            )

    except DocumentServiceError as e:
        logger.error("[remove_platform_pages] Business error: %s", str(e))
        return RemovePagesResponse(
            status="error",
            page_ids=request.page_ids,
            storage=UNIFIED_STORAGE_NAME,
            error=str(e)
        )
    except Exception as e:
        logger.error("[remove_platform_pages] Unexpected error: %s", str(e))
        return RemovePagesResponse(
            status="error",
            page_ids=request.page_ids,
            storage=UNIFIED_STORAGE_NAME,
            error=f"Internal server error: {str(e)}"
        )


@router.get("/debug_collections",
            response_model=DebugResponse,
            tags=["Отладка"])
async def debug_collections(
        document_service: DocumentService = Depends(get_document_service)
):
    """Отладочная информация о едином хранилище."""
    try:
        debug_info = await document_service.get_debug_info()

        return DebugResponse(
            storage_name=debug_info.storage_name,
            total_documents=debug_info.total_documents,
            doc_type_stats=debug_info.doc_type_stats,
            platform_stats=debug_info.platform_stats,
            service_stats=debug_info.service_stats,
            sample_metadata=debug_info.sample_metadata,
            status=debug_info.status
        )

    except DocumentServiceError as e:
        logger.error("[debug_collections] Business error: %s", str(e))
        return DebugResponse(
            storage_name=UNIFIED_STORAGE_NAME,
            error=str(e)
        )
    except Exception as e:
        logger.error("[debug_collections] Unexpected error: %s", str(e))
        return DebugResponse(
            storage_name=UNIFIED_STORAGE_NAME,
            error=f"Internal server error: {str(e)}"
        )


# Обратная совместимость - оставляем старую функцию как обертку
def remove_service_fragments(page_ids: List[str]) -> int:
    """Legacy функция для обратной совместимости с тестами."""
    service = DocumentService()
    import asyncio
    result = asyncio.run(service.remove_page_fragments(page_ids))
    return result.deleted_count