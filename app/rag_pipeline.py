# app/rag_pipeline.py

import logging
import json
import re
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup
from langchain_core.prompts import PromptTemplate
from langchain.chains.llm import LLMChain
from app.embedding_store import get_vectorstore
from app.confluence_loader import get_page_content_by_id, extract_approved_fragments
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
    """Формирует контекст для анализа, включая фрагменты из хранилища и связанные страницы.
    Исключает из контекста фрагменты, связанные с анализируемыми страницами.

    Args:
        service_code: Код сервиса.
        exclude_page_ids: Список ID страниц, исключаемых из контекста (и они же используются как список страниц для
        анализа для создания расширенного контекста).

    Returns:
        Строковый контекст, объединяющий содержимое документов.
    """
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
    logging.debug("[build_context] Filters: %s", json.dumps(filters, indent=2, ensure_ascii=False))

    embeddings_model = get_embeddings_model()

    service_store = get_vectorstore("service_pages", embedding_model=embeddings_model)
    # Выборка по фильтру всех релевантных фрагментов требований сервиса
    service_docs = service_store.similarity_search("", filter=filters)

    # Выборка фрагментов из хранилища platform_context
    platform_store = get_vectorstore("platform_context", embedding_model=embeddings_model)
    platform_docs = []
    platform_services = get_platform_services()
    for plat in platform_services:
        plat_store = platform_store
        # Выборка по фильтру всех релевантных фрагментов требований платформенных сервисов
        plat_docs = plat_store.similarity_search("", filter={"service_code": plat["code"]})
        platform_docs.extend(plat_docs)

    # Базовый контекст из векторных хранилищ
    docs = platform_docs + service_docs

    # Дополнительный контекст из подтвержденных фрагментов страниц, на которые ведут ссылки из цветных секций
    linked_docs = []
    if exclude_page_ids:
        linked_page_ids = set()
        for page_id in exclude_page_ids:
            try:
                content = get_page_content_by_id(page_id, clean_html=False)  # Получаем HTML
                if not content:
                    logging.debug("[build_context] No content for page_id=%s", page_id)
                    continue

                # Парсинг HTML для извлечения ссылок из цветных секций
                soup = BeautifulSoup(content, 'html.parser')
                for element in soup.find_all(["p", "li", "span", "div"]):
                    style = element.get("style", "").lower()
                    # Проверяем, что элемент цветной (не черный и не по умолчанию)
                    if "color" not in style or "rgb(0,0,0)" in style or "#000000" in style:
                        continue  # Пропускаем черный текст или цвет по умолчанию

                    # Ищем ссылки внутри цветного элемента
                    for link in element.find_all('a', href=True):
                        href = link['href']
                        match = re.search(r'pageId=(\d+)', href)
                        if match:
                            linked_page_id = match.group(1)
                            if linked_page_id not in exclude_page_ids and linked_page_id not in linked_page_ids:
                                linked_page_ids.add(linked_page_id)
                                logging.debug("[build_context] Found linked page_id=%s from colored section",
                                              linked_page_id)

            except Exception as e:
                logging.error("[build_context] Error processing page_id=%s: %s", page_id, str(e))

        # Ограничиваем количество связанных страниц
        max_linked_pages = 10
        linked_page_ids = list(linked_page_ids)[:max_linked_pages]
        logging.debug("[build_context] Processing %d linked page_ids", len(linked_page_ids))

        # Загружаем подтвержденные фрагменты связанных страниц
        for linked_page_id in linked_page_ids:
            try:
                linked_html = get_page_content_by_id(linked_page_id, clean_html=False)
                if linked_html:
                    approved_content = extract_approved_fragments(linked_html)
                    if approved_content:
                        linked_docs.append(approved_content)
                        logging.debug("[build_context] Added approved content for linked page_id=%s", linked_page_id)
                    else:
                        logging.debug("[build_context] No approved content for linked page_id=%s", linked_page_id)
                else:
                    logging.debug("[build_context] No content for linked page_id=%s", linked_page_id)
            except Exception as e:
                logging.error("[build_context] Error loading linked page_id=%s: %s", linked_page_id, str(e))

    # Объединяем контекст
    context_parts = [d.page_content for d in docs] + linked_docs
    context = "\n\n".join(context_parts) if context_parts else ""

    # Ограничиваем длину контекста для deepseek-chat
    max_context_length = 4000
    if len(context) > max_context_length:
        context = context[:max_context_length]
        logging.info("[build_context] Context truncated to %d characters", max_context_length)

    logging.info("[build_context] -> Context length: %d characters, linked_pages: %d",
                 len(context), len(linked_docs))
    return context


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
            logging.debug("[analyze_pages] Resolved service_code: %s", service_code)

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
        logging.debug("[analyze_pages] Context content: %s", context)

        # Создаем цепочку
        chain = build_chain(prompt_template)
        logging.debug("[analyze_pages] Chain created, input keys expected: %s", chain.input_keys)

        # Выполняем анализ всех требований одновременно
        logging.debug("[analyze_pages] Sending to chain.run, requirement:\n[%s]\n, context:\n[%s]", requirements_text, context)

        result = chain.run({"requirement": requirements_text, "context": context})
        logging.debug("[analyze_pages] Analysis result:\n[%s]", result)

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
            logging.error("[analyze_pages] Не удалось разобрать результат как JSON: %s", str(e))
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
        logging.info("[analyze_with_templates] Resolved service_code: %s", service_code)

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