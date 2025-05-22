# app/embedding_store.py

# from langchain.vectorstores import Chroma
from langchain_community.vectorstores import Chroma
# from langchain.embeddings.openai import OpenAIEmbeddings
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_core.embeddings import Embeddings
from app.config import CHROMA_PERSIST_DIR


def get_vectorstore(collection_name: str, embedding_model: Embeddings = None) -> Chroma:
    if embedding_model is None:
        embedding_model = OpenAIEmbeddings()

    return Chroma(
        collection_name=collection_name,
        embedding_function=embedding_model,
        persist_directory=CHROMA_PERSIST_DIR
    )
