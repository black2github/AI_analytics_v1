# app/llm_interface.py

from functools import lru_cache
from app.config import (
    LLM_PROVIDER,
    LLM_MODEL,
    LLM_TEMPERATURE,
    OPENAI_API_KEY,
    CLAUDE_API_KEY,
    EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL
)


def get_llm():
    if LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=LLM_MODEL,
            temperature=float(LLM_TEMPERATURE),
            api_key=OPENAI_API_KEY
        )

    elif LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=LLM_MODEL,
            temperature=float(LLM_TEMPERATURE),
            api_key=CLAUDE_API_KEY  # ANTHROPIC_API_KEY
        )

    elif LLM_PROVIDER == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=LLM_MODEL,
            temperature=float(LLM_TEMPERATURE),
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_API_URL
        )

    raise ValueError(f"Unsupported LLM provider: {LLM_PROVIDER}")


@lru_cache(maxsize=10)
def get_embeddings_model():
    """
    Кеширует модель эмбеддингов для избежания повторной инициализации.

    Returns:
        Кешированный объект модели эмбеддингов
    """
    if EMBEDDING_PROVIDER == "openai":
        from langchain_community.embeddings import OpenAIEmbeddings
        return OpenAIEmbeddings(api_key=OPENAI_API_KEY)

    elif EMBEDDING_PROVIDER == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    raise ValueError(f"Unsupported embedding provider: {EMBEDDING_PROVIDER}")


def clear_embeddings_cache():
    """Очистка кеша модели эмбеддингов (например, при изменении конфигурации)"""
    get_embeddings_model.cache_clear()


def get_embeddings_cache_info():
    """Информация о кеше модели эмбеддингов"""
    return get_embeddings_model.cache_info()