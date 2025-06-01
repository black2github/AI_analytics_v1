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


@router.post("/load_pages", tags=["Загрузка Confluence страниц требований"])
async def load_service_pages(payload: LoadRequest):
    logging.info("[load_service_pages] <- page_ids={%s}, service_code={%s}", payload.page_ids, payload.service_code)
    try:
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

@router.get("/child_pages/{page_id}", tags=["Получение дочерних страниц Confluence"],
            response_description="Список идентификаторов дочерних страниц и результат загрузки, если указан service_code")
async def get_child_pages(page_id: str, service_code: str | None = None):
    """Возвращает список идентификаторов страниц Confluence, расположенных ниже в иерархии, и, при наличии service_code, загружает их.

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
            logging.info("[get_child_pages] Calling load_service_pages with page_ids={%s}, service_code={%s}",
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


