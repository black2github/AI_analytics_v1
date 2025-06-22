# app/routes/loader.py

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict
from app.embedding_store import get_vectorstore, prepare_unified_documents
from app.llm_interface import get_embeddings_model
from app.confluence_loader import load_pages_by_ids, get_child_page_ids
from app.service_registry import resolve_service_code_from_pages_or_user, get_platform_status
from app.template_registry import store_templates
from app.config import UNIFIED_STORAGE_NAME
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class LoadRequest(BaseModel):
    page_ids: List[str]
    service_code: str | None = None
    source: str = "DBOCORPESPLN"  # Новый параметр


class TemplateLoadRequest(BaseModel):
    templates: Dict[str, str]  # {requirement_type: page_id}


class RemovePagesRequest(BaseModel):
    page_ids: List[str]
    service_code: str | None = None


@router.post("/load_pages", tags=["Загрузка Confluence страниц требований"])
async def load_service_pages(payload: LoadRequest):
    """
    Загружает ТОЛЬКО подтвержденные требования в единое хранилище.
    """
    logger.info("[load_service_pages] <- page_ids=%s, service_code=%s, source=%s",
                payload.page_ids, payload.service_code, payload.source)
    try:
        service_code = payload.service_code
        if not payload.service_code:
            service_code = resolve_service_code_from_pages_or_user(payload.page_ids)
            if not service_code:
                return {"error": "Cannot resolve service_code. Please specify explicitly."}

        # Используем единое хранилище
        embeddings_model = get_embeddings_model()
        store = get_vectorstore(UNIFIED_STORAGE_NAME, embedding_model=embeddings_model)

        # Загружаем страницы с подтвержденным содержимым
        pages = load_pages_by_ids(payload.page_ids)
        if not pages:
            return {"error": "No pages found."}

        # Фильтруем страницы с подтвержденным содержимым
        pages_with_approved_content = []
        for page in pages:
            approved_content = page.get("approved_content", "")
            if approved_content and approved_content.strip():
                pages_with_approved_content.append(page)
                logger.debug("[load_service_pages] Page %s has approved content (%d chars)",
                             page["id"], len(approved_content))
            else:
                logger.warning("[load_service_pages] Page %s has no approved content, skipping", page["id"])

        if not pages_with_approved_content:
            return {"error": "No pages with approved content found."}

        # Удаляем предыдущие фрагменты этих страниц
        page_ids_to_delete = [p["id"] for p in pages_with_approved_content]
        try:
            store.delete(where={
                "$and": [
                    {"page_id": {"$in": page_ids_to_delete}},
                    {"doc_type": {"$eq": "requirement"}}
                ]
            })
            logger.debug("[load_service_pages] Deleted existing requirement fragments for page_ids: %s",
                         page_ids_to_delete)
        except Exception as e:
            logging.warning("Could not delete existing vectors: %s", e)

        # Создаем документы с новой схемой метаданных
        docs = prepare_unified_documents(
            pages=pages_with_approved_content,
            service_code=service_code,
            doc_type="requirement",
            source=payload.source
        )

        if not docs:
            return {"error": "No documents created from approved content."}

        store.add_documents(docs)

        # Определяем платформенность для логирования
        is_platform = get_platform_status(service_code)
        platform_status = "platform" if is_platform else "regular"

        logger.info("[load_service_pages] -> %d documents indexed for %s service '%s' (only approved content)",
                    len(docs), platform_status, service_code)

        return {
            "message": f"{len(docs)} documents indexed for {platform_status} service '{service_code}' (approved content only).",
            "total_pages": len(payload.page_ids),
            "pages_with_approved_content": len(pages_with_approved_content),
            "documents_created": len(docs),
            "is_platform": is_platform,
            "storage": UNIFIED_STORAGE_NAME
        }
    except Exception as e:
        logging.exception("Error in /load_pages")
        return {"error": str(e)}


@router.post("/load_templates", tags=["Загрузка Confluence шаблонов страниц требований"])
async def load_templates(payload: TemplateLoadRequest):
    logger.info("load_templates <- dict=%s", payload.templates)
    try:
        result = store_templates(payload.templates)
        logger.info("[load_templates] -> Templates loaded: %d", result)
        return {"message": f"Templates loaded: {result}", "storage": UNIFIED_STORAGE_NAME}
    except Exception as e:
        logging.exception("Error in /load_templates")
        return {"error": str(e)}


@router.get("/child_pages/{page_id}",
            tags=["Получение дочерних страниц Confluence и их опциональная загрузка в хранилище"])
async def get_child_pages(page_id: str, service_code: str | None = None, source: str = "DBOCORPESPLN"):
    """Возвращает список идентификаторов дочерних страниц и загружает их при указании service_code."""
    logger.info("[get_child_pages] <- page_id=%s, service_code=%s, source=%s", page_id, service_code, source)
    try:
        child_page_ids = get_child_page_ids(page_id)
        if not child_page_ids:
            logger.info("[get_child_pages] No child pages found for page_id=%s", page_id)
            return {"page_ids": [], "load_result": None}

        result = {"page_ids": child_page_ids, "load_result": None}

        if service_code:
            logging.debug("[get_child_pages] Calling load_service_pages with page_ids=%s, service_code=%s",
                          child_page_ids, service_code)
            load_payload = LoadRequest(page_ids=child_page_ids, service_code=service_code, source=source)
            load_result = await load_service_pages(load_payload)
            result["load_result"] = load_result

        logger.info("[get_child_pages] -> Found %d child pages for page_id=%s", len(child_page_ids), page_id)
        return result
    except Exception as e:
        logging.exception("Error in /child_pages")
        return {"error": str(e)}


def remove_service_fragments(page_ids: List[str]) -> int:
    """
    ВОССТАНОВЛЕННАЯ ФУНКЦИЯ для совместимости с тестами.
    Удаляет из единого хранилища все фрагменты требований, связанные с указанными page_ids.

    Args:
        page_ids: Список идентификаторов страниц Confluence.

    Returns:
        Количество удаленных фрагментов.
    """
    # TODO нужно оставить только обертку. Работу с хранилищем перенести в embedding_store.py
    logger.info("[remove_service_fragments] ← page_ids=%s", page_ids)

    if not page_ids:
        logger.warning("[remove_service_fragments] Empty page_ids list provided")
        return 0

    try:
        # Получаем векторное хранилище (теперь единое)
        embedding_model = get_embeddings_model()
        vectorstore = get_vectorstore(UNIFIED_STORAGE_NAME, embedding_model=embedding_model)

        # Подсчитываем количество фрагментов до удаления
        initial_count = len(vectorstore.get()['ids'])
        logging.debug("[remove_service_fragments] Initial fragment count: %d", initial_count)

        # Удаляем фрагменты требований для указанных page_ids
        vectorstore.delete(where={
            "$and": [
                {"page_id": {"$in": page_ids}},
                {"doc_type": {"$eq": "requirement"}}
            ]
        })

        # Подсчитываем количество фрагментов после удаления
        final_count = len(vectorstore.get()['ids'])
        deleted_count = initial_count - final_count

        logger.info("[remove_service_fragments] → Deleted %d fragments for %d page_ids", deleted_count, len(page_ids))
        return deleted_count
    except Exception as e:
        logging.error("[remove_service_fragments] Error deleting fragments for page_ids=%s: %s", page_ids, str(e))
        raise


@router.post("/remove_service_pages", response_description="Удаление фрагментов страниц из единого хранилища")
async def remove_service_pages(request: RemovePagesRequest):
    """Удаляет фрагменты указанных страниц из единого хранилища."""
    logger.info("[remove_service_pages] ← page_ids=%s", request.page_ids)

    try:
        deleted_count = remove_service_fragments(request.page_ids)
        logger.info("[remove_service_pages] → Success, deleted %d fragments", deleted_count)
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "page_ids": request.page_ids,
            "storage": UNIFIED_STORAGE_NAME
        }
    except Exception as e:
        logging.error("[remove_service_pages] Error: %s", str(e))
        return {"error": str(e)}


@router.post("/remove_platform_pages", response_description="Удаление фрагментов платформенных страниц")
async def remove_platform_pages(request: RemovePagesRequest):
    """Удаляет фрагменты платформенных страниц из единого хранилища."""
    logger.info("[remove_platform_pages] <- page_ids=%s, service_code=%s", request.page_ids, request.service_code)
    try:
        if not request.service_code:
            return {"error": "service_code is required for platform pages"}

        if not get_platform_status(request.service_code):
            return {"error": f"Service {request.service_code} is not a platform service"}

        embedding_model = get_embeddings_model()
        vectorstore = get_vectorstore(UNIFIED_STORAGE_NAME, embedding_model=embedding_model)

        # Подсчитываем количество фрагментов до удаления
        initial_count = len(vectorstore.get()['ids'])

        # TODO нужно оставить только обертку. Работу с хранилищем перенести в embedding_store.py
        # Удаляем платформенные фрагменты для указанных page_ids и service_code
        vectorstore.delete(where={
            "$and": [
                {"page_id": {"$in": request.page_ids}},
                {"service_code": {"$eq": request.service_code}},
                {"doc_type": {"$eq": "requirement"}},
                {"is_platform": {"$eq": True}}
            ]
        })

        final_count = len(vectorstore.get()['ids'])
        deleted_count = initial_count - final_count

        logger.info("[remove_platform_pages] -> Success, deleted %d platform fragments", deleted_count)
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "page_ids": request.page_ids,
            "service_code": request.service_code,
            "storage": UNIFIED_STORAGE_NAME
        }
    except Exception as e:
        logging.error("[remove_platform_pages] Error: %s", str(e))
        return {"error": str(e)}


@router.get("/debug_collections", tags=["Отладка"])
async def debug_collections():
    """Отладочная информация о едином хранилище"""
    try:
        embedding_model = get_embeddings_model()
        store = get_vectorstore(UNIFIED_STORAGE_NAME, embedding_model=embedding_model)
        data = store.get()

        # Статистика по типам документов
        doc_type_stats = {}
        platform_stats = {"platform": 0, "regular": 0}
        service_stats = {}

        if data.get('metadatas'):
            for metadata in data['metadatas']:
                if metadata:
                    # Статистика по типам документов
                    doc_type = metadata.get('doc_type', 'unknown')
                    doc_type_stats[doc_type] = doc_type_stats.get(doc_type, 0) + 1

                    # Статистика по платформенности
                    is_platform = metadata.get('is_platform', False)
                    if is_platform:
                        platform_stats["platform"] += 1
                    else:
                        platform_stats["regular"] += 1

                    # Статистика по сервисам
                    service_code = metadata.get('service_code', 'unknown')
                    service_stats[service_code] = service_stats.get(service_code, 0) + 1

        collection_info = {
            "storage_name": UNIFIED_STORAGE_NAME,
            "total_documents": len(data.get('ids', [])),
            "doc_type_stats": doc_type_stats,
            "platform_stats": platform_stats,
            "service_stats": service_stats,
            "sample_metadata": data.get('metadatas', [])[:3] if data.get('metadatas') else [],
            "status": "ok"
        }

        return collection_info

    except Exception as e:
        return {"error": str(e), "storage": UNIFIED_STORAGE_NAME}