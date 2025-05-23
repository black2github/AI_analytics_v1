# app/llm_interface.py

from langchain.chat_models import ChatOpenAI
from langchain_community.embeddings import OpenAIEmbeddings
from app.config import OPENAI_API_KEY, LLM_MODEL, LLM_TEMPERATURE


def get_llm():
    return ChatOpenAI(
        model_name=LLM_MODEL,
        temperature=float(LLM_TEMPERATURE),
        openai_api_key=OPENAI_API_KEY
    )


def get_embeddings_model():
    return OpenAIEmbeddings(
        openai_api_key=OPENAI_API_KEY
    )
