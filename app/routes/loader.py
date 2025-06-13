# app/routes/loader.py

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict
from app.embedding_store import get_vectorstore, prepare_documents_for_index
from app.llm_interface import get_embeddings_model
from app.confluence_loader import load_pages_by_ids, get_child_page_ids
from app.service_registry import resolve_service_code_from_pages_or_user, is_platform_service
from app.template_registry import store_templates
import logging

logger = logging.getLogger(__name__)  # Лучше использовать __name__ для именованных логгеров

router = APIRouter()

class LoadRequest(BaseModel):
    page_ids: List[str]
    service_code: str | None = None


class TemplateLoadRequest(BaseModel):
    templates: Dict[str, str]  # {requirement_type: page_id}


class RemovePagesRequest(BaseModel):
    page_ids: List[str]
    service_code: str | None = None


@router.post("/load_pages", tags=["Загрузка Confluence страниц требований"])
async def load_service_pages(payload: LoadRequest):
    """
    ИСПРАВЛЕНО: Загружает ТОЛЬКО подтвержденные требования в векторное хранилище.
    Согласно постановке задачи, в хранилище должны быть только подтвержденные требования.
    """
    logger.info("[load_service_pages] <- page_ids={%s}, service_code={%s}", payload.page_ids, payload.service_code)
    try:
        service_code = payload.service_code
        if not payload.service_code:
            service_code = resolve_service_code_from_pages_or_user(payload.page_ids)
            if not service_code:
                return {"error": "Cannot resolve service_code. Please specify explicitly."}

        collection_name = "platform_context" if is_platform_service(service_code) else "service_pages"

        # ЗАГРУЖАЕМ СТРАНИЦЫ С ПОДТВЕРЖДЕННЫМ СОДЕРЖИМЫМ
        pages = load_pages_by_ids(payload.page_ids)
        if not pages:
            return {"error": "No pages found."}

        # ФИЛЬТРУЕМ СТРАНИЦЫ С ПОДТВЕРЖДЕННЫМ СОДЕРЖИМЫМ
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

        embeddings_model = get_embeddings_model()
        store = get_vectorstore(collection_name, embedding_model=embeddings_model)

        # УДАЛЯЕМ ПРЕДЫДУЩИЕ ФРАГМЕНТЫ ЭТИХ СТРАНИЦ (сохраняем логику)
        page_ids_to_delete = [p["id"] for p in pages_with_approved_content]
        try:
            # Используем where фильтр для более точного удаления
            store.delete(where={"page_id": {"$in": page_ids_to_delete}})
            logger.debug("[load_service_pages] Deleted existing fragments for page_ids: %s", page_ids_to_delete)
        except Exception as e:
            logging.warning("Could not delete existing vectors: {%s}", e)

        # СОЗДАЕМ ДОКУМЕНТЫ ТОЛЬКО ИЗ ПОДТВЕРЖДЕННОГО СОДЕРЖИМОГО
        docs = prepare_documents_for_approved_content(
            pages_with_approved_content,
            service_code=service_code,
            source="confluence",
            doc_type="requirement"
        )

        if not docs:
            return {"error": "No documents created from approved content."}

        store.add_documents(docs)

        logger.info("[load_service_pages] -> %d documents indexed for service {%s} (only approved content)",
                    len(docs), service_code)
        return {
            "message": f"{len(docs)} documents indexed for service '{service_code}' (approved content only).",
            "total_pages": len(payload.page_ids),
            "pages_with_approved_content": len(pages_with_approved_content),
            "documents_created": len(docs)
        }
    except Exception as e:
        logging.exception("Error in /load_pages")
        return {"error": str(e)}


def prepare_documents_for_approved_content(
        pages: list,
        service_code: str | None = None,
        source: str = "confluence",
        doc_type: str = "requirement",
        enrich_with_type: bool = False
) -> list:
    """
    НОВАЯ ФУНКЦИЯ: Создает документы ТОЛЬКО из подтвержденного содержимого страниц.
    Это гарантирует, что в векторное хранилище попадают только подтвержденные требования.
    """
    from langchain_core.documents import Document

    docs = []
    for page in pages:
        # ИСПОЛЬЗУЕМ ТОЛЬКО ПОДТВЕРЖДЕННОЕ СОДЕРЖИМОЕ
        approved_content = page.get("approved_content", "")
        if not approved_content or not approved_content.strip():
            logger.warning("[prepare_documents_for_approved_content] No approved content for page %s", page.get("id"))
            continue

        metadata = {
            "page_id": page["id"],
            "title": page["title"],
            "source": source,
            "type": doc_type,
            "content_type": "approved_only"  # Маркер, что это только подтвержденное содержимое
        }

        if service_code:
            metadata["service_code"] = service_code
        if enrich_with_type and "title" in page:
            metadata["requirement_type"] = page["title"].replace("Template: ", "").strip()

        # СОЗДАЕМ ДОКУМЕНТ ТОЛЬКО ИЗ ПОДТВЕРЖДЕННОГО СОДЕРЖИМОГО
        doc = Document(page_content=approved_content.strip(), metadata=metadata)
        docs.append(doc)

        logger.debug("[prepare_documents_for_approved_content] Created doc for page %s (%d chars approved content)",
                     page["id"], len(approved_content))

    logger.info("[prepare_documents_for_approved_content] -> Created %d documents from approved content", len(docs))
    return docs


@router.post("/load_templates", tags=["Загрузка Confluence шаблонов страниц требований"])
async def load_templates(payload: TemplateLoadRequest):
    logger.info("load_templates <- dict={%s}", payload.templates)
    try:
        result = store_templates(payload.templates)
        logger.info("[load_templates] -> Templates loaded: %d", result)
        return {"message": f"Templates loaded: {result}"}
    except Exception as e:
        logging.exception("Error in /load_templates")
        return {"error": str(e)}

@router.get("/child_pages/{page_id}", tags=["Получение дочерних страниц Confluence и их опциональная загрузка в хранилище"],
            response_description="Список идентификаторов дочерних страниц и результат загрузки, если указан service_code")
async def get_child_pages(page_id: str, service_code: str | None = None):
    """Возвращает список идентификаторов страниц Confluence, расположенных ниже в иерархии, и, при наличии service_code, загружает их.
    curl -v "http://your-api-domain.com/child_pages/12345?service_code=my_storage_service"

    Args:
        page_id: Идентификатор страницы Confluence.
        service_code: Код сервиса (опционально). Если указан, дочерние страницы загружаются через load_service_pages.

    Returns:
        JSON с списком идентификаторов дочерних страниц и, при наличии service_code, результатом их загрузки.
    """
    logger.info("[get_child_pages] <- page_id={%s}, service_code={%s}", page_id, service_code)
    try:
        # Получение идентификаторов дочерних страниц
        child_page_ids = get_child_page_ids(page_id)
        if not child_page_ids:
            logger.info("[get_child_pages] No child pages found for page_id={%s}", page_id)
            return {"page_ids": [], "load_result": None}

        result = {"page_ids": child_page_ids, "load_result": None}

        # Если указан service_code, вызываем load_service_pages
        if service_code:
            logging.debug("[get_child_pages] Calling load_service_pages with page_ids={%s}, service_code={%s}",
                         child_page_ids, service_code)
            load_payload = LoadRequest(page_ids=child_page_ids, service_code=service_code)
            load_result = await load_service_pages(load_payload)
            result["load_result"] = load_result

        logger.info("[get_child_pages] -> Found %d child pages for page_id={%s}, load_result=%s",
                     len(child_page_ids), page_id, result["load_result"])
        return result
    except Exception as e:
        logging.exception("Error in /child_pages")
        return {"error": str(e)}


def remove_service_fragments(page_ids: List[str]) -> int:
    """Удаляет из векторного хранилища service_pages все фрагменты, связанные с указанными page_ids.

    Args:
        page_ids: Список идентификаторов страниц Confluence.

    Returns:
        Количество удаленных фрагментов.
    """
    logger.info("[remove_service_fragments] ← page_ids=%s", page_ids)

    if not page_ids:
        logger.warning("[remove_service_fragments] Empty page_ids list provided")
        return 0

    try:
        # Получаем векторное хранилище
        embedding_model = get_embeddings_model()
        vectorstore = get_vectorstore("service_pages", embedding_model=embedding_model)

        # Подсчитываем количество фрагментов до удаления
        initial_count = len(vectorstore.get()['ids'])
        logging.debug("[remove_service_fragments] Initial fragment count: %d", initial_count)

        # Удаляем фрагменты, где page_id в page_ids
        vectorstore.delete(where={"page_id": {"$in": page_ids}})

        # Подсчитываем количество фрагментов после удаления
        final_count = len(vectorstore.get()['ids'])
        deleted_count = initial_count - final_count

        logger.info("[remove_service_fragments] → Deleted %d fragments for %d page_ids", deleted_count, len(page_ids))
        return deleted_count
    except Exception as e:
        logging.error("[remove_service_fragments] Error deleting fragments for page_ids=%s: %s", page_ids, str(e))
        raise


@router.post("/remove_service_pages", response_description="Удаление фрагментов страниц из векторного хранилища")
async def remove_service_pages(request: RemovePagesRequest):
    """Удаляет фрагменты указанных страниц из векторного хранилища service_pages.

    Args:
        request: Объект с списком page_ids.

    Returns:
        JSON с количеством удаленных фрагментов.
    """
    page_ids = request.page_ids
    logger.info("[remove_service_pages] ← page_ids=%s", page_ids)

    try:
        deleted_count = remove_service_fragments(page_ids)
        logger.info("[remove_service_pages] → Success, deleted %d fragments", deleted_count)
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "page_ids": page_ids
        }
    except Exception as e:
        logging.error("[remove_service_pages] Error: %s", str(e))
        return {"Ошибка при удалении страниц:": str(e)}


@router.post("/remove_platform_pages", response_description="Удаление фрагментов платформенных страниц")
async def remove_platform_pages(request: RemovePagesRequest):
    logger.info("[remove_platform_pages] <- page_ids=%s, service_code=%s", request.page_ids, request.service_code)
    try:
        if not request.service_code:
            return {"error": "service_code is required for platform pages"}
        if not is_platform_service(request.service_code):
            return {"error": f"Service {request.service_code} is not a platform service"}

        embedding_model = get_embeddings_model()
        vectorstore = get_vectorstore("platform_context", embedding_model=embedding_model)
        initial_count = len(vectorstore.get()['ids'])
        vectorstore.delete(where={
            "$and": [
                {"page_id": {"$in": request.page_ids}},
                {"service_code": {"$eq": request.service_code}}
            ]
        })
        deleted_count = initial_count - len(vectorstore.get()['ids'])
        logger.info("[remove_platform_pages] -> Success, deleted %d fragments", deleted_count)
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "page_ids": request.page_ids,
            "service_code": request.service_code
        }
    except Exception as e:
        logging.error("[remove_platform_pages] Error: %s", str(e))
        return {"error": str(e)}