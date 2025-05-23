# app/rag_pipeline.py

from langchain_core.prompts import PromptTemplate
from langchain.chains.llm import LLMChain
from langchain_openai import ChatOpenAI

from app.config import LLM_TEMPERATURE
from app.embedding_store import get_vectorstore
from app.confluence_loader import get_page_content_by_id

# Шаблон промпта
prompt_template = PromptTemplate(
    input_variables=["requirement", "context"],
    template="""
Ты — эксперт по анализу требований. Тебе предоставлены:
1. Требование: {requirement}
2. Контекст: {context}

Проанализируй требование и ответь:
- Какие части контекста необходимо учесть при реализации?
- Есть ли противоречия?
- Насколько требование совместимо с текущими платформенными и сервисными ограничениями?
"""
)

llm = ChatOpenAI(temperature=float(LLM_TEMPERATURE))
chain = LLMChain(llm=llm, prompt=prompt_template)


def analyze_text(text: str, platform_store, service_store):
    """
    Анализирует требование text на основе векторного поиска по одобренным требованиям
    из платформенного и сервисного контекста.
    """
    platform_docs = platform_store.similarity_search(text, k=5)
    service_docs = service_store.similarity_search(text, k=5)

    context_chunks = [doc.page_content for doc in platform_docs + service_docs]
    full_context = "\n\n".join(context_chunks)

    result = chain.run({"requirement": text, "context": full_context})
    return result


def analyze_pages(page_ids: list[str]):
    """
    Загружает полные тексты страниц и анализирует каждую из них в отдельности,
    используя только одобренный контекст.
    """
    platform_store = get_vectorstore("platform")
    service_store = get_vectorstore("service")

    results = []
    for page_id in page_ids:
        # Получаем ПОЛНЫЙ текст страницы (с требованиями любого цвета)
        full_text = get_page_content_by_id(page_id, clean_html=True)

        if not full_text:
            continue

        result = analyze_text(full_text, platform_store, service_store)
        results.append({"page_id": page_id, "analysis": result})

    return results
