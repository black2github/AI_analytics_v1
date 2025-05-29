# app/llm_interface.py

from langchain_anthropic import ChatAnthropic
from langchain_community.chat_models import ChatOpenAI
from langchain_community.embeddings import OpenAIEmbeddings
from app.config import OPENAI_API_KEY, LLM_MODEL, LLM_TEMPERATURE, CLAUDE_API_KEY


# def get_llm():
#     return ChatOpenAI(
#         model_name=LLM_MODEL,
#         temperature=float(LLM_TEMPERATURE),
#         openai_api_key=CLAUDE_API_KEY # OPENAI_API_KEY
#     )

def get_llm():
    return ChatAnthropic(
        model=LLM_MODEL,
        temperature=float(LLM_TEMPERATURE),
        api_key=CLAUDE_API_KEY
    )

def get_embeddings_model():
    return OpenAIEmbeddings()
