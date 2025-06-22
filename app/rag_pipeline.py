# app/rag_pipeline.py

import logging
import json
import re
from typing import Optional, List
import tiktoken
from bs4 import BeautifulSoup
from langchain_core.prompts import PromptTemplate
from langchain.chains.llm import LLMChain
from app.config import LLM_PROVIDER, TEMPLATE_ANALYSIS_PROMPT_FILE, PAGE_ANALYSIS_PROMPT_FILE, UNIFIED_STORAGE_NAME
from app.embedding_store import get_vectorstore
from app.confluence_loader import get_page_content_by_id, extract_approved_fragments
from app.llm_interface import get_llm, get_embeddings_model
from app.service_registry import (
    get_platform_services,
    resolve_service_code_from_pages_or_user,
    resolve_service_code_by_user
)
from app.template_registry import get_template_by_type
from app.semantic_search import (
    extract_key_queries,
    extract_entity_names_from_requirements,
    extract_entity_attribute_queries,
    unified_search_by_entity_title  # ОБНОВЛЕННЫЙ ИМПОРТ
)
from app.style_utils import has_colored_style
import time

llm = get_llm()
logger = logging.getLogger(__name__)


def build_chain(prompt_template: Optional[str]) -> LLMChain:
    """Создает цепочку LangChain с заданным шаблоном промпта."""
    logger.info("[build_chain] <- prompt_template=%s", bool(prompt_template))
    if prompt_template:
        if not all(var in prompt_template for var in ["{requirement}", "{context}"]):
            raise ValueError("Prompt template must include {requirement} and {context}")
        prompt = PromptTemplate(input_variables=["requirement", "context"], template=prompt_template)
    else:
        try:
            with open(PAGE_ANALYSIS_PROMPT_FILE, "r", encoding="utf-8") as file:
                template = file.read().strip()
            if not template:
                template = "Проанализируй требования: {requirement}\nКонтекст: {context}\nПредоставь детальный анализ."
            prompt = PromptTemplate(
                input_variables=["requirement", "context"],
                template=template
            )
        except FileNotFoundError:
            logger.error("[build_chain] Файл %s не найден", PAGE_ANALYSIS_PROMPT_FILE)
            raise
        except Exception as e:
            logger.error("[build_chain] Ошибка чтения %s: %s", PAGE_ANALYSIS_PROMPT_FILE, str(e))
            raise

    logger.info("[build_chain] -> prompt template created successfully")
    return LLMChain(llm=llm, prompt=prompt)


def build_context(service_code: str, requirements_text: str = "", exclude_page_ids: Optional[List[str]] = None):
    """
    Формирование контекста с использованием единого хранилища.
    Упрощенная версия с объединенным поиском.

    Args:
        service_code: Код сервиса
        requirements_text: Текст анализируемых требований для семантического поиска
        exclude_page_ids: Список ID страниц, исключаемых из контекста

    Returns:
        Строковый контекст, объединяющий содержимое документов
    """
    logger.info("[build_context] <- service_code=%s, requirements_length=%d, exclude_pages=%d",
                service_code, len(requirements_text), len(exclude_page_ids or []))

    embeddings_model = get_embeddings_model()

    # 1. Извлекаем названия сущностей для точного поиска по title
    entity_names = extract_entity_names_from_requirements(requirements_text)

    # 2. Точный поиск документов по названиям сущностей (приоритет #1)
    exact_match_docs = unified_search_by_entity_title(entity_names, service_code, exclude_page_ids, embeddings_model)

    # 3. Извлекаем ключевые запросы
    search_queries = _prepare_search_queries(requirements_text)
    entity_queries = extract_entity_attribute_queries(requirements_text)
    regular_queries = [q for q in search_queries if q not in entity_queries]

    # 4. Поиск по требованиям текущего сервиса
    service_docs = unified_service_search(
        queries=regular_queries,
        service_code=service_code,
        exclude_page_ids=exclude_page_ids,
        k_per_query=3,
        embeddings_model=embeddings_model
    )

    # 5. Поиск по платформенным требованиям
    platform_docs = unified_platform_search(
        queries=regular_queries,
        exclude_page_ids=exclude_page_ids,
        k_per_query=2,
        embeddings_model=embeddings_model,
        exclude_services=["dataModel"]  # Исключаем dataModel, так как искали точно на шаге 2
    )

    # 6. Контекст из ссылок
    linked_docs = _extract_linked_context_optimized(exclude_page_ids) if exclude_page_ids else []

    # 7. Объединяем все документы (приоритет у точных совпадений)
    all_docs = exact_match_docs + service_docs + platform_docs
    unique_docs = _fast_deduplicate_documents(all_docs)

    # 8. Формируем контекст
    context_parts = [d.page_content for d in unique_docs] + linked_docs
    context = "\n\n".join(context_parts)
    context = _smart_truncate_context(context, max_length=16000)

    logger.info("[build_context] -> exact_matches=%d, service=%d, platform=%d, linked=%d",
                len(exact_match_docs), len(service_docs), len(platform_docs), len(linked_docs))

    return context


def unified_service_search(queries: List[str], service_code: str, exclude_page_ids: Optional[List[str]],
                           k_per_query: int, embeddings_model) -> List:
    """
    Поиск требований конкретного сервиса в едином хранилище.
    """
    logger.debug("[unified_service_search] <- %d queries for service_code='%s'", len(queries), service_code)

    store = get_vectorstore(UNIFIED_STORAGE_NAME, embedding_model=embeddings_model)
    all_docs = []

    # Создаем базовый фильтр для конкретного сервиса
    base_filter = {
        "$and": [
            {"doc_type": {"$eq": "requirement"}},
            {"service_code": {"$eq": service_code}}
        ]
    }

    # Добавляем исключение страниц если нужно
    if exclude_page_ids:
        base_filter["$and"].append({"page_id": {"$nin": exclude_page_ids}})

    logger.debug("[unified_service_search] Using filter: %s", base_filter)

    for query in queries:
        try:
            docs = store.similarity_search(query, k=k_per_query, filter=base_filter)
            all_docs.extend(docs)
            logger.debug("[unified_service_search] Query '%s' found %d docs for service %s",
                         query[:50], len(docs), service_code)
        except Exception as e:
            logger.error("[unified_service_search] Error searching '%s': %s", query[:50], str(e))

    logger.debug("[unified_service_search] -> %d total docs found", len(all_docs))
    return all_docs


def unified_platform_search(queries: List[str], exclude_page_ids: Optional[List[str]],
                            k_per_query: int, embeddings_model, exclude_services: Optional[List[str]] = None) -> List:
    """
    Поиск платформенных требований в едином хранилище.
    """
    logger.debug("[unified_platform_search] <- %d queries, exclude_services=%s", len(queries), exclude_services)

    store = get_vectorstore(UNIFIED_STORAGE_NAME, embedding_model=embeddings_model)
    all_docs = []

    # Получаем список платформенных сервисов
    platform_services = get_platform_services()
    if not platform_services:
        logger.warning("[unified_platform_search] No platform services found")
        return []

    # Исключаем сервисы если нужно
    platform_codes = [svc["code"] for svc in platform_services]
    if exclude_services:
        platform_codes = [code for code in platform_codes if code not in exclude_services]
        logger.debug("[unified_platform_search] Excluded services: %s", exclude_services)

    if not platform_codes:
        logger.warning("[unified_platform_search] No platform services left after exclusions")
        return []

    # Создаем фильтр для платформенных требований
    base_filter = {
        "$and": [
            {"doc_type": {"$eq": "requirement"}},
            {"is_platform": {"$eq": True}},
            {"service_code": {"$in": platform_codes}}
        ]
    }

    # Добавляем исключение страниц если нужно
    if exclude_page_ids:
        base_filter["$and"].append({"page_id": {"$nin": exclude_page_ids}})

    logger.debug("[unified_platform_search] Using filter: %s", base_filter)

    for query in queries:
        try:
            docs = store.similarity_search(query, k=k_per_query * len(platform_codes), filter=base_filter)

            # Ограничиваем результат
            docs = docs[:k_per_query * len(platform_codes)]
            all_docs.extend(docs)

            logger.debug("[unified_platform_search] Query '%s' found %d platform docs", query[:50], len(docs))
        except Exception as e:
            logger.error("[unified_platform_search] Error searching '%s': %s", query[:50], str(e))

            # Fallback: поиск без фильтра по service_code
            try:
                fallback_filter = {
                    "$and": [
                        {"doc_type": {"$eq": "requirement"}},
                        {"is_platform": {"$eq": True}}
                    ]
                }
                if exclude_page_ids:
                    fallback_filter["$and"].append({"page_id": {"$nin": exclude_page_ids}})

                docs = store.similarity_search(query, k=k_per_query, filter=fallback_filter)
                all_docs.extend(docs)
                logger.debug("[unified_platform_search] Fallback found %d docs", len(docs))
            except Exception as e2:
                logger.error("[unified_platform_search] Fallback also failed: %s", str(e2))

    logger.info("[unified_platform_search] -> %d platform docs found", len(all_docs))
    return all_docs


def _prepare_search_queries(requirements_text: str) -> List[str]:
    """Формирует запросы для поиска"""
    if not requirements_text.strip():
        return [""]

    # Извлекаем ключевые запросы
    key_queries = extract_key_queries(requirements_text)

    if key_queries:
        logger.debug("[_prepare_search_queries] -> Using %d key queries", len(key_queries))
        return key_queries

    # Fallback: если ничего не нашли - берем первые 10 слов
    fallback_query = " ".join(requirements_text.split()[:10])
    logger.warning("[_prepare_search_queries] -> Using fallback query: %s", fallback_query)
    return [fallback_query]


def _fast_deduplicate_documents(docs: List) -> List:
    """Быстрая дедупликация документов"""
    seen_composite_keys = set()
    unique_docs = []

    for doc in docs:
        page_id = doc.metadata.get('page_id')
        content_hash = hash(doc.page_content[:100])

        composite_key = (page_id, content_hash)
        if composite_key not in seen_composite_keys:
            seen_composite_keys.add(composite_key)
            unique_docs.append(doc)

    logger.debug("[_fast_deduplicate_documents] Deduplicated %d -> %d documents", len(docs), len(unique_docs))
    return unique_docs


def _smart_truncate_context(context: str, max_length: int) -> str:
    """Умное обрезание контекста по границам предложений"""
    if len(context) <= max_length:
        return context

    truncated = context[:max_length]
    last_period = truncated.rfind('.')
    if last_period > max_length * 0.8:
        truncated = truncated[:last_period + 1]

    logger.debug("[_smart_truncate_context] Truncated context from %d to %d chars", len(context), len(truncated))
    return truncated


def _extract_linked_context_optimized(exclude_page_ids: List[str]) -> List[str]:
    """
    Извлечение контекста по ссылкам ТОЛЬКО из неподтвержденных (цветных) фрагментов.
    """
    logger.info("[_extract_linked_context_optimized] <- Processing %d pages for links", len(exclude_page_ids))

    if not exclude_page_ids:
        return []

    linked_docs = []
    max_linked_pages = 3
    max_pages = 5

    for page_id in exclude_page_ids[:max_pages]:
        try:
            content = get_page_content_by_id(page_id, clean_html=False)
            if not content:
                continue

            # Ищем ссылки ТОЛЬКО в неподтвержденных фрагментах
            linked_page_ids = _extract_links_from_unconfirmed_fragments(content, exclude_page_ids)
            logger.debug("[_extract_linked_context_optimized] Found %d links in unconfirmed fragments",
                         len(linked_page_ids))

            for linked_page_id in linked_page_ids[:2]:
                if len(linked_docs) >= max_linked_pages:
                    break

                linked_content = _get_approved_content_cached(linked_page_id)
                if linked_content and linked_content.strip():
                    linked_docs.append(linked_content)
                    logger.debug("[_extract_linked_context_optimized] Added content from linked page '%s'",
                                 linked_page_id)

            if len(linked_docs) >= max_linked_pages:
                break

        except Exception as e:
            logger.error("[_extract_linked_context_optimized] Error processing page_id=%s: %s", page_id, str(e))

    logger.info("[_extract_linked_context_optimized] -> Found %d linked documents", len(linked_docs))
    return linked_docs


def _extract_links_from_unconfirmed_fragments(html_content: str, exclude_page_ids: List[str]) -> List[str]:
    """Извлекает ссылки ТОЛЬКО из неподтвержденных (цветных) фрагментов требований."""
    soup = BeautifulSoup(html_content, 'html.parser')
    found_page_ids = set()
    exclude_set = set(exclude_page_ids)

    for element in soup.find_all(["p", "li", "span", "div", "td", "th"]):
        if not has_colored_style(element):
            continue

        element_links = _extract_confluence_links_from_element(element)
        for linked_page_id in element_links:
            if linked_page_id not in exclude_set and linked_page_id not in found_page_ids:
                found_page_ids.add(linked_page_id)

    return list(found_page_ids)


def _extract_confluence_links_from_element(element) -> List[str]:
    """Извлекает все ссылки на страницы Confluence из конкретного элемента."""
    import re
    page_ids = []

    # 1. Обычные HTML ссылки с pageId в URL
    for link in element.find_all('a', href=True):
        href = link['href']
        patterns = [
            r'pageId=(\d+)',
            r'/pages/viewpage\.action\?pageId=(\d+)',
            r'/display/[^/]+/[^?]*\?pageId=(\d+)',
            r'/wiki/spaces/[^/]+/pages/(\d+)/'
        ]

        for pattern in patterns:
            match = re.search(pattern, href)
            if match:
                page_ids.append(match.group(1))
                break

    # 2. Confluence макросы ссылок
    for ac_link in element.find_all('ac:link'):
        ri_page = ac_link.find('ri:page')
        if ri_page:
            page_id = ri_page.get('ri:content-id')
            if page_id:
                page_ids.append(page_id)

    # 3. Прямые ri:page теги
    for ri_page in element.find_all('ri:page'):
        page_id = ri_page.get('ri:content-id')
        if page_id:
            page_ids.append(page_id)

    return list(set(page_ids))


def _get_approved_content_cached(page_id: str) -> Optional[str]:
    """Кешированное получение подтвержденного контента"""
    try:
        html_content = get_page_content_by_id(page_id, clean_html=False)
        if html_content:
            approved_content = extract_approved_fragments(html_content)
            return approved_content.strip() if approved_content else None
    except Exception as e:
        logger.error("[_get_approved_content_cached] Error loading page_id=%s: %s", page_id, str(e))
    return None


def _extract_json_from_llm_response(response: str) -> Optional[str]:
    """
    Извлекает JSON из ответа LLM, удаляя лишний текст и форматирование.
    """
    if not response:
        return None

    # Убираем markdown форматирование
    response = response.strip()
    response = response.strip("```json").strip("```").strip()

    # ИСПРАВЛЕНИЕ: Исправляем порядок и жадность паттернов
    json_patterns = [
        # 1. ИСПРАВЛЕНО: Жадный поиск JSON в markdown блоке
        r'```json\s*(\{.*\})\s*```',  # БЫЛО: (\{.*?\}) - СТАЛО: (\{.*\})
        # 2. Простой поиск от первой { до последней } (жадный)
        r'(\{.*\})',
        # 3. Поиск сбалансированных скобок (как fallback)
        r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})',
    ]

    for pattern in json_patterns:
        matches = re.findall(pattern, response, re.DOTALL | re.MULTILINE)
        for match in matches:
            try:
                # Проверяем, что это валидный JSON
                json.loads(match)
                logger.debug("[_extract_json_from_llm_response] Found valid JSON with pattern: %s", pattern)
                return match.strip()
            except json.JSONDecodeError:
                continue

    # Если ничего не найдено, пробуем найти JSON вручную
    try:
        # Ищем первую открывающую скобку
        start = response.find('{')
        if start == -1:
            return None

        # Ищем соответствующую закрывающую скобку
        brace_count = 0
        end = start

        for i, char in enumerate(response[start:], start):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end = i
                    break

        if brace_count == 0:
            candidate = response[start:end + 1]
            # Проверяем валидность
            json.loads(candidate)
            logger.debug("[_extract_json_from_llm_response] Found valid JSON by manual parsing")
            return candidate.strip()

    except (json.JSONDecodeError, ValueError):
        pass

    logging.warning("[_extract_json_from_llm_response] No valid JSON found in response")
    return None


_encoding = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Подсчитывает количество токенов в тексте"""
    if LLM_PROVIDER == "deepseek":
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    else:
        try:
            return len(_encoding.encode(text))
        except Exception as e:
            logger.error("[count_tokens] Error counting tokens: %s", str(e))
            return len(text.split())


def analyze_text(text: str, prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    logger.info("[analyze_text] <- text length=%d, service_code=%s", len(text), service_code)
    if not service_code:
        service_code = resolve_service_code_by_user()
        logger.info("[analyze_text] Resolved service_code: %s", service_code)

    chain = build_chain(prompt_template)
    context = build_context(service_code, requirements_text=text)

    try:
        result = chain.run({"requirement": text, "context": context})
        logger.info("[analyze_text] -> result length=%d", len(result))
        return result
    except Exception as e:
        if "token limit" in str(e).lower():
            logger.error("[analyze_text] Token limit exceeded: %s", str(e))
            return {"error": "Превышен лимит токенов модели. Уменьшите объем текста или контекста."}
        raise


def analyze_pages(page_ids: List[str], prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    logger.info("[analyze_pages] <- page_ids=%s, service_code=%s", page_ids, service_code)
    try:
        if not service_code:
            service_code = resolve_service_code_from_pages_or_user(page_ids)
            logger.debug("[analyze_pages] Resolved service_code: %s", service_code)

        requirements = []
        valid_page_ids = []
        max_tokens = 65000
        max_context_tokens = max_tokens // 2
        current_tokens = 0
        template = prompt_template or open(PAGE_ANALYSIS_PROMPT_FILE, "r", encoding="utf-8").read().strip()
        template_tokens = count_tokens(template)

        # Собираем страницы до превышения лимита токенов
        for page_id in page_ids:
            content = get_page_content_by_id(page_id, clean_html=True)
            if content:
                req_text = f"Page ID: {page_id}\n{content}"
                req_tokens = count_tokens(req_text)
                if current_tokens + req_tokens + template_tokens < max_tokens - max_context_tokens:
                    requirements.append({"page_id": page_id, "content": content})
                    valid_page_ids.append(page_id)
                    current_tokens += req_tokens
                else:
                    logging.warning("[analyze_pages] Excluded page %s due to token limit", page_id)
                    break

        if not requirements:
            logging.warning("[analyze_pages] No valid requirements found, service code: %s", service_code)
            return []

        requirements_text = "\n\n".join(
            [f"Page ID: {req['page_id']}\n{req['content']}" for req in requirements]
        )

        # Используем новую функцию построения контекста
        context = build_context(service_code, requirements_text=requirements_text, exclude_page_ids=page_ids)

        context_tokens = count_tokens(context)
        if context_tokens > max_context_tokens:
            logging.warning("[analyze_pages] Context too large (%d tokens), limiting analysis", context_tokens)
            return [{"page_id": pid, "analysis": "Анализ невозможен: контекст слишком большой"} for pid in
                    valid_page_ids]
            # return [{"Страница №": pid, "Анализ": "Анализ невозможен: контекст слишком большой"} for pid in
            #         valid_page_ids]

        # Проверяем общий размер
        full_prompt = PromptTemplate(
            input_variables=["requirement", "context"],
            template=template
        ).format(requirement=requirements_text, context=context)
        total_tokens = count_tokens(full_prompt)

        logger.debug("[analyze_pages] Tokens: requirements=%d, context=%d, total=%d",
                     current_tokens, context_tokens, total_tokens)

        if total_tokens > max_tokens:
            logging.warning("[analyze_pages] Total tokens (%d) exceed limit (%d)", total_tokens, max_tokens)
            return [{"page_id": pid, "analysis": "Анализ невозможен: превышен лимит токенов"} for pid in valid_page_ids]
            # return [{"Страница №": pid, "Анализ": "Анализ невозможен: превышен лимит токенов"} for pid in valid_page_ids]

        chain = build_chain(prompt_template)
        try:
            result = chain.run({"requirement": requirements_text, "context": context})
            logger.debug("[analyze_pages] Raw LLM response: '%s'", result)

            # Извлекаем и парсим JSON
            cleaned_result = _extract_json_from_llm_response(result)
            if not cleaned_result:
                logger.error("[analyze_pages] No valid JSON found in LLM response")
                return [{"page_id": pid, "analysis": "Ошибка: LLM не вернул корректный JSON"} for pid in valid_page_ids]
                # return [{"Страница №": pid, "Анализ": "Ошибка: LLM не вернул корректный JSON"} for pid in valid_page_ids]

            try:
                parsed_result = json.loads(cleaned_result)
                logger.info("[analyze_pages] Successfully parsed JSON response")
            except json.JSONDecodeError as json_err:
                logger.error("[analyze_pages] JSON decode error: %s", str(json_err))
                return [{"page_id": valid_page_ids[0] if valid_page_ids else "unknown", "analysis": result}]

            if not isinstance(parsed_result, dict):
                logger.error("[analyze_pages] Result is not a dictionary")
                return [{"page_id": pid, "analysis": "Ошибка: неожиданный формат ответа LLM"} for pid in valid_page_ids]
                # return [{"Страница №": pid, "Анализ": "Ошибка: неожиданный формат ответа LLM"} for pid in valid_page_ids]

            results = []
            logger.debug("[analyze_pages] results: '%s'", parsed_result)
            for page_id in valid_page_ids:
                analysis = parsed_result.get(page_id, f"Анализ для страницы {page_id} не найден")
                results.append({"page_id": page_id, "analysis": analysis})
                # results.append({"Страница №": page_id, "Анализ": analysis})

            logger.info("[analyze_pages] -> Result count: %d", len(results))
            return results

        except Exception as e:
            if "token limit" in str(e).lower():
                logger.error("[analyze_pages] Token limit exceeded: %s", str(e))
                return [{"page_id": pid, "analysis": "Ошибка: превышен лимит токенов модели"} for pid in valid_page_ids]
                # return [{"Страница №": pid, "Анализ": "Ошибка: превышен лимит токенов модели"} for pid in valid_page_ids]
            logger.error("[analyze_pages] Error in LLM chain: %s", str(e))
            raise
    except Exception as e:
        logging.exception("[analyze_pages] Error in analyze_pages")
        raise


def analyze_with_templates(items: List[dict], prompt_template: Optional[str] = None,
                           service_code: Optional[str] = None):
    """
    Анализирует новые требования и их соответствие шаблонам с передачей шаблона в LLM.
    Обновлено для работы с единым хранилищем.
    """
    logger.info("[analyze_with_templates] <- items count: %d, service_code: %s", len(items), service_code)

    if not service_code:
        page_ids = [item["page_id"] for item in items]
        service_code = resolve_service_code_from_pages_or_user(page_ids)
        logger.info("[analyze_with_templates] Resolved service_code: %s", service_code)

    results = []
    template_chain = build_template_analysis_chain(prompt_template)

    for item in items:
        requirement_type = item["requirement_type"]
        page_id = item["page_id"]

        logger.info("[analyze_with_templates] Processing page_id: %s, type: %s", page_id, requirement_type)

        # Получаем контент страницы и шаблон
        content = get_page_content_by_id(page_id, clean_html=True)
        template_html = get_template_by_type(requirement_type)

        if not content or not template_html:
            logger.warning("[analyze_with_templates] Missing content or template for page %s", page_id)
            results.append({
                "page_id": page_id,
                "requirement_type": requirement_type,
                "template_analysis": {
                    "error": "Отсутствует содержимое страницы или шаблон",
                    "template_available": bool(template_html),
                    "content_available": bool(content)
                },
                "legacy_formatting_issues": []
            })
            continue

        template_content = template_html

        # Строим контекст с использованием единого хранилища
        context = build_context(
            service_code=service_code,
            requirements_text=content,
            exclude_page_ids=[page_id]
        )

        # Быстрая структурная проверка (legacy поддержка)
        legacy_formatting_issues = _perform_legacy_structure_check(template_html, content)

        try:
            logger.debug(
                "[analyze_with_templates] Sending to LLM: template=%d chars, content=%d chars, context=%d chars",
                len(template_content), len(content), len(context))

            llm_result = template_chain.run({
                "requirement": content,
                "template": template_content,
                "context": context
            })

            # Парсим JSON ответ от LLM
            try:
                template_analysis = _parse_llm_template_response(llm_result)
                logger.info("[analyze_with_templates] LLM analysis completed for page %s", page_id)
            except Exception as json_error:
                logger.error("[analyze_with_templates] Failed to parse LLM JSON for page %s: %s", page_id,
                             str(json_error))
                template_analysis = {
                    "error": "Не удалось разобрать ответ LLM",
                    "raw_response": llm_result[:500],
                    "parse_error": str(json_error)
                }

            results.append({
                "page_id": page_id,
                "requirement_type": requirement_type,
                "template_analysis": template_analysis,
                "legacy_formatting_issues": legacy_formatting_issues,
                "template_used": requirement_type,
                "analysis_timestamp": time.time(),
                "storage_used": UNIFIED_STORAGE_NAME
            })

        except Exception as e:
            logger.error("[analyze_with_templates] Error analyzing page %s: %s", page_id, str(e))

            if "token limit" in str(e).lower():
                error_msg = "Превышен лимит токенов модели"
            else:
                error_msg = f"Ошибка анализа: {str(e)}"

            results.append({
                "page_id": page_id,
                "requirement_type": requirement_type,
                "template_analysis": {
                    "error": error_msg,
                    "error_type": "llm_error"
                },
                "legacy_formatting_issues": legacy_formatting_issues
            })

    logger.info("[analyze_with_templates] -> Completed analysis for %d items", len(results))
    return results


def _perform_legacy_structure_check(template_html: str, content: str) -> List[str]:
    """Выполняет быструю структурную проверку (legacy код для обратной совместимости)"""
    try:
        from markdownify import markdownify
        from bs4 import BeautifulSoup

        template_md = markdownify(template_html, heading_style="ATX")
        content_md = markdownify(content, heading_style="ATX")
        template_soup = BeautifulSoup(template_md, 'html.parser')
        content_soup = BeautifulSoup(content_md, 'html.parser')

        formatting_issues = []

        # Проверка заголовков
        template_headers = [h.get_text().strip() for h in template_soup.find_all(['h1', 'h2', 'h3'])]
        content_headers = [h.get_text().strip() for h in content_soup.find_all(['h1', 'h2', 'h3'])]
        if set(template_headers) != set(content_headers):
            formatting_issues.append(
                f"Несоответствие заголовков: ожидаются {template_headers}, найдены {content_headers}")

        # Проверка таблиц
        template_tables = template_soup.find_all('table')
        content_tables = content_soup.find_all('table')
        if len(template_tables) != len(content_tables):
            formatting_issues.append(
                f"Несоответствие количества таблиц: ожидается {len(template_tables)}, найдено {len(content_tables)}")

        return formatting_issues

    except Exception as e:
        logger.warning("[_perform_legacy_structure_check] Error in legacy check: %s", str(e))
        return [f"Ошибка структурной проверки: {str(e)}"]


def _parse_llm_template_response(llm_response: str) -> dict:
    """Парсит JSON ответ от LLM"""
    json_content = _extract_json_from_llm_response(llm_response)

    if not json_content:
        raise ValueError("No valid JSON found in LLM response")

    parsed_result = json.loads(json_content)

    # Валидируем структуру ответа
    required_sections = ["template_compliance", "content_quality", "system_integration", "recommendations", "summary"]
    missing_sections = [section for section in required_sections if section not in parsed_result]

    if missing_sections:
        logger.warning("[_parse_llm_template_response] Missing sections in LLM response: %s", missing_sections)
        for section in missing_sections:
            parsed_result[section] = {"error": f"Section {section} missing from LLM response"}

    return parsed_result


def build_template_analysis_chain(custom_prompt: Optional[str] = None) -> LLMChain:
    """Создает цепочку LangChain для анализа соответствия шаблону."""
    logger.info("[build_template_analysis_chain] <- custom_prompt provided: %s", bool(custom_prompt))

    if custom_prompt:
        required_vars = ["{requirement}", "{template}", "{context}"]
        if not all(var in custom_prompt for var in required_vars):
            raise ValueError(f"Custom prompt template must include {required_vars}")
        template = custom_prompt
    else:
        try:
            with open(TEMPLATE_ANALYSIS_PROMPT_FILE, "r", encoding="utf-8") as file:
                template = file.read().strip()
            if not template:
                raise ValueError("Template analysis prompt file is empty")
        except FileNotFoundError:
            logger.error("[build_template_analysis_chain] Файл %s не найден", TEMPLATE_ANALYSIS_PROMPT_FILE)
            template = """
Проанализируй соответствие требований шаблону:

ШАБЛОН: {template}
ТРЕБОВАНИЯ: {requirement}
КОНТЕКСТ: {context}

Верни анализ в формате JSON с оценками соответствия, качества и рекомендациями.
"""
        except Exception as e:
            logger.error("[build_template_analysis_chain] Ошибка чтения %s: %s", TEMPLATE_ANALYSIS_PROMPT_FILE, str(e))
            raise

    prompt = PromptTemplate(
        input_variables=["requirement", "template", "context"],
        template=template
    )

    logger.info("[build_template_analysis_chain] -> Template analysis chain created")
    return LLMChain(llm=llm, prompt=prompt)