# app/embedding_store.py

from langchain_chroma import Chroma
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_core.embeddings import Embeddings
from app.config import CHROMA_PERSIST_DIR
from langchain_core.documents import Document


def get_vectorstore(collection_name: str, embedding_model: Embeddings = None) -> Chroma:
    if embedding_model is None:
        embedding_model = OpenAIEmbeddings()

    return Chroma(
        collection_name=collection_name,
        embedding_function=embedding_model,
        persist_directory=CHROMA_PERSIST_DIR
    )


# Метод для централизованного управления (дальнейшего расширения) логики метаданных, такой как
# форматирования, chunking и пр.
def prepare_documents_for_index(pages: list) -> list:
    """
    Извлекает только одобренные требования для индексации.
    """
    documents = []
    for page in pages:
        content = page.get("approved_content")
        if not content:
            continue

        metadata = {
            "page_id": page["id"],
            "title": page["title"],
        }

        doc = Document(page_content=content, metadata=metadata)
        documents.append(doc)

    return documents

