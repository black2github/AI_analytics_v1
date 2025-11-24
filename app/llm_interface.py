# app/llm_interface.py
import logging
from functools import lru_cache
from app.config import (
    LLM_PROVIDER,
    LLM_MODEL,
    LLM_TEMPERATURE,
    OPENAI_API_KEY,
    ANTHROPIC_API_KEY,
    EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL, OLLAMA_API_URL, OLLAMA_API_KEY, KIMI_API_KEY, KIMI_API_URL
)

logger = logging.getLogger(__name__)

def get_llm():
    logger.debug("[get_llm] <-.")
    import os
    current_provider = os.getenv("LLM_PROVIDER", LLM_PROVIDER)  # fallback на импортированное
    llm_model = os.getenv("LLM_MODEL", LLM_MODEL)  # fallback на импортированное
    llm_temperature = os.getenv("LLM_TEMPERATURE", LLM_TEMPERATURE)  # fallback на импортированное

    if current_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=llm_model,
            temperature=float(llm_temperature),
            api_key=OPENAI_API_KEY
        )

    elif current_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=llm_model,
            temperature=float(llm_temperature),
            api_key=ANTHROPIC_API_KEY
        )

    elif current_provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=llm_model,
            temperature=float(llm_temperature),
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_API_URL
        )

    elif current_provider == "ollama":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=llm_model,
            temperature=float(llm_temperature),
            api_key=OLLAMA_API_KEY,
            base_url=OLLAMA_API_URL
        )

    elif current_provider == "kimi":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=llm_model,
            temperature=float(llm_temperature),
            api_key=KIMI_API_KEY,
            base_url=KIMI_API_URL
        )

    raise ValueError(f"Unsupported LLM provider: {current_provider}")


@lru_cache(maxsize=10)
def get_embeddings_model():
    """
    Кеширует модель эмбеддингов для избежания повторной инициализации.

    Returns:
        Кешированный объект модели эмбеддингов
    """
    logger.debug("[get_embeddings_model] <-.")
    if EMBEDDING_PROVIDER == "openai":
        from langchain_community.embeddings import OpenAIEmbeddings
        return OpenAIEmbeddings(api_key=OPENAI_API_KEY)

    elif EMBEDDING_PROVIDER == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    raise ValueError(f"Unsupported embedding provider: {EMBEDDING_PROVIDER}")


def clear_embeddings_cache():
    """Очистка кеша модели эмбеддингов (например, при изменении конфигурации)"""
    logger.debug("[clear_embeddings_cache] <-.")
    get_embeddings_model.cache_clear()


def get_embeddings_cache_info():
    """Информация о кеше модели эмбеддингов"""
    logger.debug("[get_embeddings_cache_info] <-.")
    return get_embeddings_model.cache_info()