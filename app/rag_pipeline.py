# app/rag_pipeline.py

import logging
import json
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

llm = get_llm()

def build_chain(prompt_template: Optional[str]) -> LLMChain:
    if prompt_template:
        prompt = PromptTemplate(
            input_variables=["requirement", "context"],
            template=prompt_template
        )
    else:
        with open("page_prompt_template.txt", "r", encoding="utf-8") as file:
           template = file.read()
        template = template
        prompt = PromptTemplate(
            input_variables=["requirement", "context"],
            template=template
        )
    return LLMChain(llm=llm, prompt=prompt)


def build_context(service_code: str, exclude_page_ids: Optional[List[str]] = None):
    # Фильтр для отбора всех фрагментов требований, относящихся к сервису, за исключением фрагментов,
    # созданных из страниц, идентификаторы которых переданы в качестве аргументов.
    # Формируем составной фильтр
    filters = {
        "$and": [
            {"service_code": {"$eq": service_code}}
        ]
    }
    if exclude_page_ids:
        filters["$and"].append({"page_id": {"$nin": exclude_page_ids}})

    # Распечатка filters в текстовом виде
    logging.info("Filters: %s", json.dumps(filters, indent=2, ensure_ascii=False))

    embeddings_model = get_embeddings_model()

    service_store = get_vectorstore("service_pages", embedding_model=embeddings_model)
    # Выборка по фильтру всех релевантных фрагментов требований сервиса
    service_docs = service_store.similarity_search("", filter=filters)

    platform_store = get_vectorstore("platform_context", embedding_model=embeddings_model)
    platform_docs = []
    platform_services = get_platform_services()
    for plat in platform_services:
        plat_store = platform_store
        # Выборка по фильтру всех релевантных фрагментов требований платформенных сервисов
        plat_docs = plat_store.similarity_search("", filter={"service_code": plat["code"]})
        platform_docs.extend(plat_docs)

    # Создание общего контекста
    docs = platform_docs + service_docs
    return "\n\n".join([d.page_content for d in docs])


def analyze_text(text: str, prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    if not service_code:
        service_code = resolve_service_code_by_user()

    chain = build_chain(prompt_template)
    context = build_context(service_code)
    logging.info("[rag_pipeline]: {%s}, service code: %s", text, service_code)
    return chain.run({"requirement": text, "context": context})


def analyze_pages(page_ids: List[str], prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    """Анализирует все страницы требований вместе, учитывая общий контекст.

    Args:
        page_ids: Список ID страниц для анализа.
        prompt_template: Шаблон промпта (если None, используется дефолтный).
        service_code: Код сервиса (если None, определяется автоматически).

    Returns:
        Список результатов анализа для каждой страницы в формате:
        [{"page_id": "id1", "analysis": "текст анализа"}, ...]
    """
    # Определение service_code, если не передан
    if not service_code:
        service_code = resolve_service_code_from_pages_or_user(page_ids)

    # Сбор содержимого всех страниц
    requirements = []
    valid_page_ids = []
    for page_id in page_ids:
        content = get_page_content_by_id(page_id, clean_html=True)
        if content:
            requirements.append(content)
            valid_page_ids.append(page_id)

    # Если нет валидного содержимого, вернуть пустой результат
    if not requirements:
        return []

    # Объединяем содержимое всех страниц в один текст
    combined_requirements = "\n\n".join(requirements)

    # Формируем контекст, исключая все переданные page_ids
    context = build_context(service_code, exclude_page_ids=page_ids)

    logging.info("Combined requirements: %s", combined_requirements)
    logging.info("Context: %s", context)

    # Создаем цепочку
    chain = build_chain(prompt_template)

    # Выполняем анализ всех требований одновременно
    result = chain.run({"requirement": combined_requirements, "context": context})

    # Формируем результат, привязывая анализ к page_ids
    # Предполагаем, что результат анализа применим ко всем страницам
    # results = [{"page_id": page_id, "analysis": result} for page_id in valid_page_ids]

    # Разделяем результат анализа по страницам
    # Парсим, предполагая, что ИИ возвращает структурированный ответ.
    try:
        parsed_result = json.loads(result)
        results = [{"page_id": page_id, "analysis": parsed_result.get(page_id, result)} for page_id in valid_page_ids]
    except json.JSONDecodeError:
        results = [{"page_id": page_id, "analysis": result} for page_id in valid_page_ids]

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