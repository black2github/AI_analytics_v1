from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from app.confluence_loader import load_pages_by_ids
from app.embedding_store import get_vectorstore
from app.llm_interface import get_embeddings_model
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


class LoadRequest(BaseModel):
    page_ids: List[str]


@router.post("/load_platform_context")
async def load_platform_context(payload: LoadRequest):
    try:
        pages = load_pages_by_ids(payload.page_ids)
        embeddings_model = get_embeddings_model()
        store = get_vectorstore(collection_name="platform_context")
        store.add_texts(
            [p["content"] for p in pages],
            metadatas=[{"title": p["title"], "id": p["id"]} for p in pages],
            embeddings=embeddings_model
        )
        return {"message": f"{len(pages)} platform pages added to vector store."}
    except Exception as e:
        logger.exception("Error in /load_platform_context")
        return {"error": str(e)}


@router.post("/load_service_pages")
async def load_service_pages(payload: LoadRequest):
    try:
        pages = load_pages_by_ids(payload.page_ids)
        embeddings_model = get_embeddings_model()
        store = get_vectorstore(collection_name="service_pages")
        store.add_texts(
            [p["content"] for p in pages],
            metadatas=[{"title": p["title"], "id": p["id"]} for p in pages],
            embeddings=embeddings_model
        )
        return {"message": f"{len(pages)} service pages added to vector store."}
    except Exception as e:
        logger.exception("Error in /load_service_pages")
        return {"error": str(e)}
