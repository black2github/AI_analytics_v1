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
    logging.info("[load_service_pages] <- page_ids={%s}, service_code={%s}", payload.page_ids, payload.service_code)
    try:
        service_code = payload.service_code
        if not payload.service_code:
            service_code = resolve_service_code_from_pages_or_user(payload.page_ids)
            if not service_code:
                return {"error": "Cannot resolve service_code. Please specify explicitly."}

        collection_name = "platform_context" if is_platform_service(service_code) else "service_pages"

        pages = load_pages_by_ids(payload.page_ids)
        if not pages:
            return {"error": "No pages found."}

        embeddings_model = get_embeddings_model()
        store = get_vectorstore(collection_name, embedding_model=embeddings_model)

        try:
            store.delete(ids=[p["id"] for p in pages])
        except Exception as e:
            logging.warning("Could not delete existing vectors: {%s}", e)

        docs = prepare_documents_for_index(pages, service_code=service_code, source="confluence", doc_type="requirement")
        store.add_documents(docs)

        logging.info("[load_service_pages] -> %d documents indexed for service {%s}", len(docs), service_code)
        return {"message": f"{len(docs)} documents indexed for service '{service_code}'."}
    except Exception as e:
        logging.exception("Error in /load_pages")
        return {"error": str(e)}


@router.post("/load_templates", tags=["Загрузка Confluence шаблонов страниц требований"])
async def load_templates(payload: TemplateLoadRequest):
    logging.info("load_templates <- dict={%s}", payload.templates)
    try:
        result = store_templates(payload.templates)
        logging.info("[load_templates] -> Templates loaded: %d", result)
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
    logging.info("[get_child_pages] <- page_id={%s}, service_code={%s}", page_id, service_code)
    try:
        # Получение идентификаторов дочерних страниц
        child_page_ids = get_child_page_ids(page_id)
        if not child_page_ids:
            logging.info("[get_child_pages] No child pages found for page_id={%s}", page_id)
            return {"page_ids": [], "load_result": None}

        result = {"page_ids": child_page_ids, "load_result": None}

        # Если указан service_code, вызываем load_service_pages
        if service_code:
            logging.debug("[get_child_pages] Calling load_service_pages with page_ids={%s}, service_code={%s}",
                         child_page_ids, service_code)
            load_payload = LoadRequest(page_ids=child_page_ids, service_code=service_code)
            load_result = await load_service_pages(load_payload)
            result["load_result"] = load_result

        logging.info("[get_child_pages] -> Found %d child pages for page_id={%s}, load_result=%s",
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
    logging.info("[remove_service_fragments] ← page_ids=%s", page_ids)

    if not page_ids:
        logging.warning("[remove_service_fragments] Empty page_ids list provided")
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

        logging.info("[remove_service_fragments] → Deleted %d fragments for %d page_ids", deleted_count, len(page_ids))
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
    logging.info("[remove_service_pages] ← page_ids=%s", page_ids)

    try:
        deleted_count = remove_service_fragments(page_ids)
        logging.info("[remove_service_pages] → Success, deleted %d fragments", deleted_count)
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
    logging.info("[remove_platform_pages] <- page_ids=%s, service_code=%s", request.page_ids, request.service_code)
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
        logging.info("[remove_platform_pages] -> Success, deleted %d fragments", deleted_count)
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "page_ids": request.page_ids,
            "service_code": request.service_code
        }
    except Exception as e:
        logging.error("[remove_platform_pages] Error: %s", str(e))
        return {"error": str(e)}