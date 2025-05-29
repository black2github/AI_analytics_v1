# app/rag_pipeline.py
import logging
from typing import Optional, List, Dict, Any
from langchain_core.prompts import PromptTemplate
from langchain.chains.llm import LLMChain
from app.embedding_store import get_vectorstore
from app.confluence_loader import get_page_content_by_id
from app.llm_interface import get_llm, get_embeddings_model
from app.service_registry import (
    get_platform_services,
    resolve_service_code_from_pages_or_user,
    resolve_service_code_by_user
)
from app.template_registry import get_template_by_type

# Шаблон промпта по умолчанию
default_prompt_template = PromptTemplate(
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

llm = get_llm()
logger = logging.getLogger(__name__)


def build_chain(prompt_template: Optional[str]) -> LLMChain:
    if prompt_template:
        prompt = PromptTemplate(
            input_variables=["requirement", "context"],
            template=prompt_template
        )
    else:
        prompt = default_prompt_template
    return LLMChain(llm=llm, prompt=prompt)


def build_context(service_code: str, exclude_page_ids: Optional[List[str]] = None):

    filters: Dict[str, Any] = {"service_code": service_code}
    if exclude_page_ids:
        filters["page_id"] = {"$nin": exclude_page_ids}

    # embeddings_model = get_embeddings_model()
    # service_store = get_vectorstore("service_pages", embedding_model=embeddings_model)
    # platform_store = get_vectorstore("platform_context", embedding_model=embeddings_model)
    service_store = get_vectorstore("service_pages")
    platform_store = get_vectorstore("platform_context")

    service_docs = service_store.similarity_search("", filter=filters)
    platform_services = get_platform_services()
    platform_docs = []

    for plat in platform_services:
        plat_store = platform_store
        plat_docs = plat_store.similarity_search("", filter={"service_code": plat["code"]})
        platform_docs.extend(plat_docs)

    docs = platform_docs + service_docs
    return "\n\n".join([d.page_content for d in docs])


def analyze_text(text: str, prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    if not service_code:
        service_code = resolve_service_code_by_user()

    logger.info(f"[rag_pipeline] point 1")
    chain = build_chain(prompt_template)
    logger.info(f"[rag_pipeline] point 2")
    context = build_context(service_code)
    logger.info(f"[rag_pipeline]: {text}, service code: {service_code}")
    return chain.run({"requirement": text, "context": context})


def analyze_pages(page_ids: List[str], prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    if not service_code:
        service_code = resolve_service_code_from_pages_or_user(page_ids)

    results = []
    for page_id in page_ids:
        content = get_page_content_by_id(page_id, clean_html=True)
        if not content:
            continue

        chain = build_chain(prompt_template)
        context = build_context(service_code, exclude_page_ids=[page_id])
        result = chain.run({"requirement": content, "context": context})
        results.append({"page_id": page_id, "analysis": result})

    return results


def analyze_with_templates(items: List[dict], prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    if not service_code:
        page_ids = [item["page_id"] for item in items]
        service_code = resolve_service_code_from_pages_or_user(page_ids)

    results = []
    for item in items:
        requirement_type = item["requirement_type"]
        page_id = item["page_id"]

        content = get_page_content_by_id(page_id, clean_html=True)
        template = get_template_by_type(requirement_type)
        if not content or not template:
            continue

        chain = build_chain(prompt_template)
        context = build_context(service_code, exclude_page_ids=[page_id])

        full_prompt = {
            "requirement": content,
            "context": context
        }

        result = chain.run(full_prompt)
        results.append({
            "page_id": page_id,
            "requirement_type": requirement_type,
            "analysis": result
        })

    return results