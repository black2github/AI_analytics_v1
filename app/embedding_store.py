# app/embedding_store.py

import logging
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document
from langchain_core.documents import Document
from app.config import CHROMA_PERSIST_DIR, EMBEDDING_MODEL, EMBEDDING_PROVIDER, OPENAI_API_KEY

logger = logging.getLogger(__name__)  # Лучше использовать __name__ для именованных логгеров

def get_vectorstore(collection_name: str, embedding_model: Embeddings = None) -> Chroma:
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


def prepare_documents_for_approved_content(
        pages: list,
        service_code: str | None = None,
        source: str = "confluence",
        doc_type: str = "requirement",
        enrich_with_type: bool = False
) -> list:
    """
    Создает документы ТОЛЬКО из подтвержденного содержимого страниц.
    Это гарантирует, что в векторное хранилище попадают только подтвержденные требования.
    """
    logger.debug("[prepare_documents_for_approved_content] <- pages count='%d', service code='%s', source='%s', doc type='%s', enrich='%s'",
                len(pages), service_code, source, doc_type, enrich_with_type)
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
            metadata["requirement_type"] = page["title"].replace("[DRAFT] ", "").strip()

        logger.debug("[prepare_documents_for_approved_content] creating doc: page_id=%s, title='%s', source='%s', type='%s', service_code='%s' ",
                     page["id"], page["title"], source, doc_type, service_code)

        # СОЗДАЕМ ДОКУМЕНТ ТОЛЬКО ИЗ ПОДТВЕРЖДЕННОГО СОДЕРЖИМОГО
        doc = Document(page_content=approved_content.strip(), metadata=metadata)
        docs.append(doc)

        logger.debug("[prepare_documents_for_approved_content] Created doc for page %s (%d chars approved content)",
                     page["id"], len(approved_content))

    logger.info("[prepare_documents_for_approved_content] -> Created %d documents from approved content", len(docs))
    return docs

def prepare_documents_for_index(
    pages: list,
    service_code: str | None = None,
    source: str = "confluence",
    doc_type: str = "requirement",
    enrich_with_type: bool = False
) -> list[Document]:
    """
    Создает документы из содержимого страниц.
    """
    logger.debug("[prepare_documents_for_index] <- pages count='%d', service code='%s', source='%s', doc type='%s', enrich='%s'",
                len(pages), service_code, source, doc_type, enrich_with_type)
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

        logger.debug("[prepare_documents_for_index] creating doc: page_id=%s, title='%s', source='%s', type='%s', service_code='%s' ",
                     page["id"], page["title"], source, doc_type, service_code)

        doc = Document(page_content=content, metadata=metadata)
        docs.append(doc)

    logger.info("[prepare_documents_for_index] -> Created %d documents from approved content", len(docs))
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

    logger.info("[embedding_store] Using embedding model: {%s}, dimension: {%s}", name, dim)
    return model