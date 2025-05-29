# app/routes/loader.py

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict
from app.embedding_store import get_vectorstore, prepare_documents_for_index
from app.llm_interface import get_embeddings_model
from app.confluence_loader import load_pages_by_ids
from app.service_registry import resolve_service_code_from_pages_or_user, is_platform_service
from app.template_registry import store_templates
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


class LoadRequest(BaseModel):
    page_ids: List[str]
    service_code: str | None = None


class TemplateLoadRequest(BaseModel):
    templates: Dict[str, str]  # {requirement_type: page_id}


@router.post("/load_pages", tags=["Загрузка Confluence страниц требований"])
async def load_service_pages(payload: LoadRequest):
    try:
        service_code = resolve_service_code_from_pages_or_user(payload.page_ids)
        if not service_code:
            return {"error": "Cannot resolve service_code. Please specify explicitly."}

        collection_name = "platform_context" if is_platform_service(service_code) else "service_pages"

        pages = load_pages_by_ids(payload.page_ids)
        if not pages:
            return {"error": "No pages found."}

        # embeddings_model = get_embeddings_model()
        # store = get_vectorstore(collection_name, embedding_model=embeddings_model)
        store = get_vectorstore(collection_name)

        try:
            store.delete(ids=[p["id"] for p in pages])
        except Exception as e:
            logger.warning(f"Could not delete existing vectors: {e}")

        docs = prepare_documents_for_index(pages, service_code=service_code, source="confluence", doc_type="requirement")
        store.add_documents(docs)

        return {"message": f"{len(docs)} documents indexed for service '{service_code}'."}
    except Exception as e:
        logger.exception("Error in /load_pages")
        return {"error": str(e)}


@router.post("/load_templates", tags=["Загрузка Confluence шаблонов страниц требований"])
async def load_templates(payload: TemplateLoadRequest):
    try:
        result = store_templates(payload.templates)
        return {"message": f"Templates loaded: {result}"}
    except Exception as e:
        logger.exception("Error in /load_templates")
        return {"error": str(e)}
