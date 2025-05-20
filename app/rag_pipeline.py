from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from langchain.chat_models import ChatOpenAI
from app.embedding_store import get_vectorstore
from app.confluence_loader import get_page_content_by_id


# Шаблон промпта
prompt_template = PromptTemplate(
    input_variables=["requirement", "context"],
    template="""
Ты — эксперт по требованиям. Тебе предоставлены:
1. Требование: {requirement}
2. Контекст: {context}

Проанализируй требование и ответь:
- Какие части контекста необходимо учесть при реализации?
- Есть ли противоречия?
- Насколько требование совместимо с текущими платформенными и сервисными ограничениями?
"""
)

# Инициализация LLMChain
llm = ChatOpenAI(temperature=0.2)
chain = LLMChain(llm=llm, prompt=prompt_template)


def analyze_text(text: str, platform_store, service_store):
    platform_docs = platform_store.similarity_search(text, k=5)
    service_docs = service_store.similarity_search(text, k=5)

    context_chunks = [doc.page_content for doc in platform_docs + service_docs]
    full_context = "\n\n".join(context_chunks)

    result = chain.run({"requirement": text, "context": full_context})
    return result


def analyze_pages(page_ids: list[str]):
    platform_store = get_vectorstore("platform")
    service_store = get_vectorstore("service")

    results = []
    for page_id in page_ids:
        content = get_page_content_by_id(page_id)
        result = analyze_text(content, platform_store, service_store)
        results.append({"page_id": page_id, "analysis": result})
    return results
