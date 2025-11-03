# app/embedding_store.py

import logging
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document
from app.config import CHROMA_PERSIST_DIR, EMBEDDING_MODEL, EMBEDDING_PROVIDER, OPENAI_API_KEY, UNIFIED_STORAGE_NAME
from app.service_registry import get_platform_status

logger = logging.getLogger(__name__)


def get_vectorstore(collection_name: str, embedding_model: Embeddings = None) -> Chroma:
    logger.debug("[get_vectorstore] <- collection_name = '%s', embedding_model= '%s'", collection_name, embedding_model)

    if embedding_model is None:
        embedding_model = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    # Проверка совместимости фильтров
    try:
        import chromadb
        chroma_version = chromadb.__version__

        # Для проблемных версий ChromaDB логируем предупреждение
        if chroma_version.startswith(("0.4.", "0.5.")):
            logger.warning("ChromaDB %s may have filter limitations. Consider upgrading to 0.6+", chroma_version)

    except Exception as e:
        logger.debug("Could not check ChromaDB version: %s", e)

    return Chroma(
        collection_name=collection_name,
        embedding_function=embedding_model,
        persist_directory=CHROMA_PERSIST_DIR
    )


def prepare_unified_documents(
        pages: list,
        service_code: str,
        doc_type: str = "requirement",
        requirement_type: str = None,
        source: str = "DBOCORPESPLN"
) -> list[Document]:
    """
    Создает документы для единого хранилища с новой схемой метаданных.
    """
    logger.debug("[prepare_unified_documents] <- Processing %d pages, service_code='%s', doc_type='%s'",
                 len(pages), service_code, doc_type)

    docs = []
    is_platform = get_platform_status(service_code) if doc_type == "requirement" else False

    for page in pages:
        content = page.get("approved_content", "")
        if not content or not content.strip():
            logger.warning("[prepare_unified_documents] No approved content for page %s", page.get("id"))
            continue

        # Создаем метаданные по новой схеме
        metadata = {
            "doc_type": doc_type,
            "is_platform": is_platform,
            "service_code": service_code,
            "title": page["title"],
            "source": source,
            "page_id": page["id"]
        }

        # ИЗМЕНЯЕМ ЛОГИКУ ДОБАВЛЕНИЯ requirement_type
        if requirement_type:
            # Приоритет у параметра метода
            metadata["requirement_type"] = requirement_type
        elif page.get("requirement_type"):
            # Используем тип из страницы
            metadata["requirement_type"] = page["requirement_type"]
        # Если ни того, ни другого нет - оставляем без requirement_type

        logger.debug("[prepare_unified_documents] Creating doc: page_id=%s, title='%s', requirement_type='%s'",
                     page["id"], page["title"], metadata.get("requirement_type"))

        doc = Document(page_content=content.strip(), metadata=metadata)
        docs.append(doc)

    logger.info("[prepare_unified_documents] -> Created %d documents for unified storage", len(docs))
    return docs


# Совместимость - оставляем старые функции как обертки
def prepare_documents_for_approved_content(
        pages: list,
        service_code: str | None = None,
        source: str = "DBOCORPESPLN",
        doc_type: str = "requirement",
        enrich_with_type: bool = False
) -> list:
    """Legacy wrapper для обратной совместимости"""
    return prepare_unified_documents(
        pages=pages,
        service_code=service_code or "unknown",
        doc_type=doc_type,
        source=source
    )


def prepare_documents_for_index(
        pages: list,
        service_code: str | None = None,
        source: str = "DBOCORPESPLN",
        doc_type: str = "requirement",
        enrich_with_type: bool = False
) -> list[Document]:
    """Legacy wrapper для обратной совместимости"""
    return prepare_unified_documents(
        pages=pages,
        service_code=service_code or "unknown",
        doc_type=doc_type,
        source=source
    )


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

    logger.info("[embedding_store] Using embedding model: {%s}, dimension: {%s}", name, dim)
    return model