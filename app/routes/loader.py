# app/routes/loader.py

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from app.confluence_loader import load_pages_by_ids
from app.embedding_store import get_vectorstore, prepare_documents_for_index
from app.llm_interface import get_embeddings_model
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


class LoadRequest(BaseModel):
    page_ids: List[str]


def _load_and_replace(collection_name: str, page_ids: List[str], log_context: str):
    pages = load_pages_by_ids(page_ids)
    if not pages:
        logger.warning(f"No pages found for {log_context}. Skipping.")
        return {"message": "No pages loaded."}

    embeddings_model = get_embeddings_model()
    store = get_vectorstore(collection_name=collection_name, embedding_model=embeddings_model)

    # Удаляем существующие записи по page_ids
    try:
        store.delete(ids=[p["id"] for p in pages])
    except Exception as e:
        logger.warning(f"Could not delete existing vectors in {collection_name}: {e}")

    # Сохраняем одобренные требования.
    docs = prepare_documents_for_index(pages)
    store.add_documents(docs)
    return {"message": f"{len(pages)} {log_context} pages added to vector store."}


@router.post("/load_platform_context")
async def load_platform_context(payload: LoadRequest):
    try:
        return _load_and_replace("platform_context", payload.page_ids, "platform")
    except Exception as e:
        logger.exception("Error in /load_platform_context")
        return {"error": str(e)}


@router.post("/load_service_pages")
async def load_service_pages(payload: LoadRequest):
    try:
        return _load_and_replace("service_pages", payload.page_ids, "service")
    except Exception as e:
        logger.exception("Error in /load_service_pages")
        return {"error": str(e)}
