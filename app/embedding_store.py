# app/embedding_store.py

from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain_core.embeddings import Embeddings
import os

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")


def get_vectorstore(collection_name: str, embedding_model: Embeddings = None) -> Chroma:
    if embedding_model is None:
        embedding_model = OpenAIEmbeddings()

    return Chroma(
        collection_name=collection_name,
        embedding_function=embedding_model,
        persist_directory=CHROMA_PATH
    )
