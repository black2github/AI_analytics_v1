# app/embedding_store.py

import logging
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document
from app.config import CHROMA_PERSIST_DIR, EMBEDDING_MODEL, EMBEDDING_PROVIDER, OPENAI_API_KEY


def get_vectorstore(collection_name: str, embedding_model: Embeddings = None) -> Chroma:
    if embedding_model is None:
        embedding_model = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL) # было   embedding_model = OpenAIEmbeddings()
    return Chroma(
        collection_name=collection_name,
        embedding_function=embedding_model,
        persist_directory=CHROMA_PERSIST_DIR
    )


def prepare_documents_for_index(
    pages: list,
    service_code: str | None = None,
    source: str = "confluence",
    doc_type: str = "requirement",
    enrich_with_type: bool = False
) -> list[Document]:
    docs = []
    for page in pages:
        content = page.get("approved_content")
        if not content:
            continue

        metadata = {
            "page_id": page["id"],
            "title": page["title"],
            "source": source,
            "type": doc_type,
        }

        if service_code:
            metadata["service_code"] = service_code
        if enrich_with_type and "title" in page:
            metadata["requirement_type"] = page["title"].replace("Template: ", "").strip()

        doc = Document(page_content=content, metadata=metadata)
        docs.append(doc)
    return docs

# Вспомогательная функция — получает размерность эмбеддингов
def get_embedding_model(name: str = EMBEDDING_MODEL) -> Embeddings:
    if EMBEDDING_PROVIDER == "openai":
        from langchain_community.embeddings import OpenAIEmbeddings
        model = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
        dim = 1536  # фиксировано
    elif EMBEDDING_PROVIDER == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings
        model = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        # Получаем пример эмбеддинга, чтобы узнать размерность
        test = model.embed_query("test")
        dim = len(test)

    logging.info("[embedding_store] Using embedding model: {%s}, dimension: {%s}", name, dim)
    return model