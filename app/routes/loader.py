# app/routes/loader.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict  # ДОБАВЛЕН ИМПОРТ Dict
from app.services.document_service import DocumentService
import logging
from app.llm_interface import get_embeddings_cache_info, clear_embeddings_cache

logger = logging.getLogger(__name__)
router = APIRouter()

# Инициализируем сервис (простое создание без DI)
document_service = DocumentService()


class LoadRequest(BaseModel):
    page_ids: List[str]
    service_code: Optional[str] = None
    source: str = "DBOCORPESPLN"


class TemplateLoadRequest(BaseModel):
    templates: Dict[str, str]


class RemovePagesRequest(BaseModel):
    page_ids: List[str]
    service_code: Optional[str] = None


@router.post("/load_pages", tags=["Загрузка Confluence страниц требований"])
async def load_service_pages(payload: LoadRequest):
    """Загружает ТОЛЬКО подтвержденные требования в единое хранилище."""
    logger.info("[load_service_pages] <- page_ids=%s, service_code=%s, source=%s",
                payload.page_ids, payload.service_code, payload.source)
    try:
        result = document_service.load_approved_pages(
            page_ids=payload.page_ids,
            service_code=payload.service_code,
            source=payload.source
        )

        platform_status = "platform" if result["is_platform"] else "regular"

        # ИСПРАВЛЕНИЕ: Возвращаем структуру совместимую с тестами
        return {
            "message": f"{result['documents_created']} documents indexed for {platform_status} service '{result['service_code']}' (approved content only).",
            "total_pages": result["total_pages"],
            "pages_with_approved_content": result["pages_with_approved_content"],
            "documents_created": result["documents_created"],
            "is_platform": result["is_platform"],
            "storage": result["storage"]
        }
    except ValueError as e:
        logger.error("[load_service_pages] Validation error: %s", str(e))
        return {"error": str(e)}
    except Exception as e:
        logger.exception("[load_service_pages] Unexpected error")
        return {"error": str(e)}


@router.post("/load_templates", tags=["Загрузка Confluence шаблонов страниц требований"])
async def load_templates(payload: TemplateLoadRequest):
    logger.info("load_templates <- dict=%s", payload.templates)
    try:
        result = document_service.load_templates_to_storage(payload.templates)
        return {
            "message": f"Templates loaded: {result}",
            "storage": "unified_requirements"
        }
    except Exception as e:
        logger.exception("Error in /load_templates")
        return {"error": str(e)}


@router.get("/child_pages/{page_id}",
            tags=["Получение дочерних страниц Confluence и их опциональная загрузка в хранилище"])
async def get_child_pages(page_id: str, service_code: Optional[str] = None, source: str = "DBOCORPESPLN"):
    """Возвращает список идентификаторов дочерних страниц и загружает их при указании service_code."""
    logger.info("[get_child_pages] <- page_id=%s, service_code=%s, source=%s", page_id, service_code, source)
    try:
        result = document_service.get_child_pages_with_optional_load(page_id, service_code, source)
        logger.info("[get_child_pages] -> Found %d child pages", len(result["page_ids"]))
        return result
    except Exception as e:
        logger.exception("Error in /child_pages")
        return {"error": str(e)}


@router.post("/remove_service_pages", response_description="Удаление фрагментов страниц из единого хранилища")
async def remove_service_pages(request: RemovePagesRequest):
    """Удаляет фрагменты указанных страниц из единого хранилища."""
    logger.info("[remove_service_pages] <- page_ids=%s", request.page_ids)
    try:
        deleted_count = document_service.remove_page_fragments(request.page_ids)
        logger.info("[remove_service_pages] -> Success, deleted %d fragments", deleted_count)
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "page_ids": request.page_ids,
            "storage": "unified_requirements"
        }
    except Exception as e:
        logger.error("[remove_service_pages] Error: %s", str(e))
        return {"error": str(e)}


@router.post("/remove_platform_pages", response_description="Удаление фрагментов платформенных страниц")
async def remove_platform_pages(request: RemovePagesRequest):
    """Удаляет фрагменты платформенных страниц из единого хранилища."""
    logger.info("[remove_platform_pages] <- page_ids=%s, service_code=%s", request.page_ids, request.service_code)
    try:
        deleted_count = document_service.remove_platform_page_fragments(request.page_ids, request.service_code)
        logger.info("[remove_platform_pages] -> Success, deleted %d platform fragments", deleted_count)
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "page_ids": request.page_ids,
            "service_code": request.service_code,
            "storage": "unified_requirements"
        }
    except ValueError as e:
        logger.error("[remove_platform_pages] Validation error: %s", str(e))
        return {"error": str(e)}
    except Exception as e:
        logger.error("[remove_platform_pages] Error: %s", str(e))
        return {"error": str(e)}


@router.get("/debug_collections", tags=["Отладка"])
async def debug_collections():
    """Отладочная информация о едином хранилище"""
    logger.info("[debug_collections] <-.")
    try:
        return document_service.get_storage_info()
    except Exception as e:
        return {"error": str(e), "storage": "unified_requirements"}


# Сохраняем функцию remove_service_fragments для обратной совместимости с тестами
def remove_service_fragments(page_ids: List[str]) -> int:
    """DEPRECATED: Используйте DocumentService.remove_page_fragments"""
    logger.info("Deprecated [remove_service_fragments] <- page_ids=%s.", page_ids)
    return document_service.remove_page_fragments(page_ids)

from app.page_cache import clear_page_cache, get_cache_info

@router.get("/cache_info", tags=["Кеширование"])
async def cache_info():
    """Информация о состоянии кеша страниц"""
    logger.info("[cache_info] <-.")
    return get_cache_info()


@router.post("/clear_cache", tags=["Кеширование"])
async def clear_cache():
    """Очистка кеша страниц"""
    logger.info("[clear_cache] <-.")
    clear_page_cache()
    return {"message": "Cache cleared successfully"}

@router.get("/embedding_cache_info", tags=["Кеширование"])
async def embedding_cache_info():
    """Информация о кеше модели эмбеддингов"""
    logger.info("[embedding_cache_info] <-.")
    cache_info = get_embeddings_cache_info()
    return {
        "hits": cache_info.hits,
        "misses": cache_info.misses,
        "current_size": cache_info.currsize,
        "max_size": cache_info.maxsize
    }

@router.post("/clear_embedding_cache", tags=["Кеширование"])
async def clear_embedding_cache():
    """Очистка кеша модели эмбеддингов"""
    logger.info("[clear_embedding_cache] <-.")
    clear_embeddings_cache()
    return {"message": "Embedding model cache cleared successfully"}