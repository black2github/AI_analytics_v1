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
    """Создает цепочку LangChain с заданным шаблоном промпта."""
    logging.info("[build_chain] <- prompt_template={%s}" % prompt_template)
    if prompt_template:
        prompt = PromptTemplate(
            input_variables=["requirement", "context"],
            template=prompt_template
        )
    else:
        try:
            with open("page_prompt_template.txt", "r", encoding="utf-8") as file:
                template = file.read().strip()  # Удаляем лишние пробелы и переносы
            prompt = PromptTemplate(
                input_variables=["requirement", "context"],
                template=template
            )
        except FileNotFoundError:
            logging.error("[build_chain] Файл page_prompt_template.txt не найден")
            raise
        except Exception as e:
            logging.error("[build_chain] Ошибка чтения page_prompt_template.txt: %s", str(e))
            raise

    # Логируем шаблон промпта для отладки
    logging.info("[build_chain] -> prompt template: %s", prompt.template)
    logging.info("[build_chain] -> prompt input variables: %s", prompt.input_variables)

    return LLMChain(llm=llm, prompt=prompt)


def build_context(service_code: str, exclude_page_ids: Optional[List[str]] = None):
    # Фильтр для отбора всех фрагментов требований, относящихся к сервису, за исключением фрагментов,
    # созданных из страниц, идентификаторы которых переданы в качестве аргументов.
    # Формируем составной фильтр
    logging.info("[build_context] <- service_code={%s}, exclude_page_ids={%s}", service_code, exclude_page_ids)
    if exclude_page_ids:
        filters = {
            "$and": [
                {"service_code": {"$eq": service_code}},
                {"page_id": {"$nin": exclude_page_ids}}
            ]
        }
    else:
        filters = {"service_code": {"$eq": service_code}}   # {"service_code": service_code}

    # Распечатка filters в текстовом виде
    logging.info("[build_context] Filters: %s", json.dumps(filters, indent=2, ensure_ascii=False))

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

    context = "\n\n".join([d.page_content for d in docs])
    logging.info("[build_context]: -> {%s}", context)
    return "\n\n".join([d.page_content for d in docs])


def analyze_text(text: str, prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    logging.info("[analyze_text] <- text={%s}, prompt_template=..., service_code={%s}", text, service_code)
    if not service_code:
        service_code = resolve_service_code_by_user()
        logging.info("[analyze_text] Resolved service_code: %s", service_code)

    chain = build_chain(prompt_template)
    context = build_context(service_code)
    logging.info("[analyze_text] text=\n{%s}, context=\n{%s}", text, context)
    result = chain.run({"requirement": text, "context": context})
    # cleaned_result = result.strip().strip("```json\n").strip("```")
    logging.info("[analyze_text] -> result={%s}", result)
    return result


def analyze_pages(page_ids: List[str], prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    """Анализирует все страницы требований вместе, учитывая общий контекст.

    Args:
        page_ids: Список ID страниц для анализа.
        prompt_template: Шаблон промпта (если None, используется дефолтный).
        service_code: Код сервиса (если None, определяется автоматически).

    Returns:
        Список резanalyze_pagesультатов анализа для каждой страницы в формате:
        [{"page_id": "id1", "analysis": "текст анализа"}, ...]
    """
    logging.info("[analyze_pages] <- page_ids={%s}, service_code={%s}", page_ids, service_code)
    try:
        # Определение service_code, если не передан
        if not service_code:
            service_code = resolve_service_code_from_pages_or_user(page_ids)
            logging.info("[analyze_pages] Resolved service_code: %s", service_code)

        # Сбор содержимого всех страниц
        requirements = []
        valid_page_ids = []
        for page_id in page_ids:
            content = get_page_content_by_id(page_id, clean_html=True)
            if content:
                requirements.append({"page_id": page_id, "content": content})
                valid_page_ids.append(page_id)

        # Если нет валидного содержимого, вернуть пустой результат
        if not requirements:
            logging.warning("[analyze_pages] No valid requirements found, service code: %s", service_code)
            return []

        # Форматирование требований с метками page_id
        requirements_text = "\n\n".join(
            [f"Page ID: {req['page_id']}\n{req['content']}" for req in requirements]
        )

        # Формируем контекст, исключая все переданные page_ids
        context = build_context(service_code, exclude_page_ids=page_ids)
        logging.info("[analyze_pages] Context content: %s", context)

        # Создаем цепочку
        chain = build_chain(prompt_template)
        logging.info("[analyze_pages] Chain created, input keys expected: %s", chain.input_keys)

        # Выполняем анализ всех требований одновременно
        logging.info("[analyze_pages] Sending to chain.run, requirement:\n[%s]\n, context:\n[%s]", requirements_text, context)

        result = chain.run({"requirement": requirements_text, "context": context})
        logging.info("[analyze_pages] Analysis result:\n[%s]", result)

        # Формируем результат, привязывая анализ к page_ids
        # Парсим, предполагая, что ИИ возвращает структурированный ответ.
        try:
            # Удаление обрамления markdown, если присутствует
            cleaned_result = result.strip().strip("```json\n").strip("```")
            parsed_result = json.loads(cleaned_result)
            if not isinstance(parsed_result, dict):
                logging.error("[analyze_pages] Result is not a dictionary: %s", result)
                raise ValueError("Ожидался JSON-объект с ключами page_id")

            # Формирование результатов
            results = []
            for page_id in valid_page_ids:
                analysis = parsed_result.get(page_id, "Анализ не найден для этой страницы")
                results.append({"page_id": page_id, "analysis": analysis})
        except json.JSONDecodeError as e:
            logging.warning("[analyze_pages] Не удалось разобрать результат как JSON: %s", str(e))
            results = [{"page_id": page_id, "analysis": result} for page_id in valid_page_ids]
        except ValueError as e:
            logging.error("[analyze_pages] Неверный формат результата: %s", str(e))
            results = [{"page_id": page_id, "analysis": f"Ошибка: {str(e)}"} for page_id in valid_page_ids]

        logging.info("[analyze_pages] -> Result:\n[%s]", results)
        return results
    except Exception as e:
        logging.exception("[analyze_pages] Ошибка в /analyze")
        raise

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