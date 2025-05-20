# app/llm_interface.py

import os
from langchain.chat_models import ChatOpenAI
from langchain.embeddings.openai import OpenAIEmbeddings


def get_llm():
    model_name = os.getenv("LLM_MODEL", "gpt-4")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))

    return ChatOpenAI(
        model_name=model_name,
        temperature=temperature,
        openai_api_key=os.getenv("OPENAI_API_KEY")
    )


def get_embeddings_model():
    return OpenAIEmbeddings(
        openai_api_key=os.getenv("OPENAI_API_KEY")
    )
