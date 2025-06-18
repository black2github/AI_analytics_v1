# app/rag_pipeline.py

import logging
import json
import re
from typing import Optional, List
import markdownify
from markdownify import markdownify
import tiktoken
from bs4 import BeautifulSoup
from langchain_core.prompts import PromptTemplate
from langchain.chains.llm import LLMChain
from app.config import LLM_PROVIDER
from app.embedding_store import get_vectorstore
from app.confluence_loader import get_page_content_by_id, extract_approved_fragments
from app.llm_interface import get_llm, get_embeddings_model
from app.service_registry import (
    get_platform_services,
    resolve_service_code_from_pages_or_user,
    resolve_service_code_by_user
)
from app.template_registry import get_template_by_type
from app.semantic_search import extract_key_queries, deduplicate_documents, extract_entity_names_from_requirements, \
    _search_by_entity_title, extract_entity_attribute_queries
from app.style_utils import has_colored_style

llm = get_llm()
logger = logging.getLogger(__name__)


def build_chain(prompt_template: Optional[str]) -> LLMChain:
    """Создает цепочку LangChain с заданным шаблоном промпта."""
    logger.info("[build_chain] <- prompt_template={%s}", prompt_template)
    if prompt_template:
        if not all(var in prompt_template for var in ["{requirement}", "{context}"]):
            raise ValueError("Prompt template must include {requirement} and {context}")
        prompt = PromptTemplate(input_variables=["requirement", "context"], template=prompt_template)
    else:
        try:
            with open("page_prompt_template.txt", "r", encoding="utf-8") as file:
                template = file.read().strip()
            if not template:
                template = "Проанализируй требования: {requirement}\nКонтекст: {context}\nПредоставь детальный анализ."
            prompt = PromptTemplate(
                input_variables=["requirement", "context"],
                template=template
            )
        except FileNotFoundError:
            logger.error("[build_chain] Файл page_prompt_template.txt не найден")
            raise
        except Exception as e:
            logger.error("[build_chain] Ошибка чтения page_prompt_template.txt: %s", str(e))
            raise

    logger.info("[build_chain] -> prompt template: %s", prompt.template)
    logger.info("[build_chain] -> prompt input variables: %s", prompt.input_variables)

    return LLMChain(llm=llm, prompt=prompt)


def build_context(service_code: str, requirements_text: str = "", exclude_page_ids: Optional[List[str]] = None):
    """
    Оптимизированная версия формирования контекста с улучшенной производительностью.
    УЛУЧШЕННАЯ версия с точным поиском моделей данных.
        Args:
        service_code: Код сервиса
        requirements_text: Текст анализируемых требований для семантического поиска
        exclude_page_ids: Список ID страниц, исключаемых из контекста

    Returns:
        Строковый контекст, объединяющий содержимое документов
    """
    logger.info("[build_context] <- service_code=%s, requirements_length=%d", service_code, len(requirements_text))

    embeddings_model = get_embeddings_model()

    # 1. ИЗВЛЕКАЕМ НАЗВАНИЯ СУЩНОСТЕЙ для точного поиска по title
    entity_names = extract_entity_names_from_requirements(requirements_text)

    # 2. ТОЧНЫЙ ПОИСК ПО НАЗВАНИЯМ СУЩНОСТЕЙ (приоритет #1)
    exact_match_docs = _search_by_entity_title(entity_names, service_code, exclude_page_ids, embeddings_model)

    # 3. ИЗВЛЕКАЕМ КЛЮЧЕВЫЕ ЗАПРОСЫ (включая entity queries)
    search_queries = _prepare_search_queries(requirements_text)
    entity_queries = extract_entity_attribute_queries(requirements_text)
    regular_queries = [q for q in search_queries if q not in entity_queries]

    # 4. ДОПОЛНИТЕЛЬНЫЙ ПОИСК МОДЕЛЕЙ ДАННЫХ (если точный поиск не дал результатов)
    additional_model_docs = []
    if len(exact_match_docs) < len(entity_names):  # Не все сущности найдены точно
        additional_model_docs = _search_data_models(entity_queries, service_code, exclude_page_ids, embeddings_model)

    # 5. ОБЫЧНЫЙ ПОИСК ПО СЕРВИСНЫМ ТРЕБОВАНИЯМ
    service_filters = _create_filters(service_code, exclude_page_ids)
    service_docs = batch_service_search(
        store_name="service_pages",
        queries=regular_queries,
        filters=service_filters,
        k_per_query=3,
        embeddings_model=embeddings_model
    )

    # 6. ПОИСК ПО ПЛАТФОРМЕННЫМ ТРЕБОВАНИЯМ (исключая dataModel)
    try:
        platform_docs = batch_platform_search(
            queries=regular_queries,
            exclude_page_ids=exclude_page_ids,
            k_per_query=2,
            embeddings_model=embeddings_model,
            exclude_services=["dataModel"]  # Исключаем, так как искали модель данных ранее на шаге 2
        )

        logger.debug("[build_context] Filtered out dataModel, remaining platform docs: %d", len(platform_docs))

    except Exception as e:
        logger.error("[build_context] Platform search failed: %s", str(e))
        platform_docs = []

    # 7. КОНТЕКСТ ИЗ ССЫЛОК
    linked_docs = _extract_linked_context_optimized(exclude_page_ids) if exclude_page_ids else []

    # 8. ОБЪЕДИНЕНИЕ С МАКСИМАЛЬНЫМ ПРИОРИТЕТОМ ДЛЯ ТОЧНЫХ СОВПАДЕНИЙ
    all_docs = exact_match_docs + additional_model_docs + service_docs + platform_docs
    unique_docs = _fast_deduplicate_documents(all_docs)

    # 9. ФОРМИРОВАНИЕ КОНТЕКСТА
    context_parts = [d.page_content for d in unique_docs] + linked_docs
    context = "\n\n".join(context_parts)
    context = _smart_truncate_context(context, max_length=16000)

    logger.info("[build_context] -> exact_matches=%d, additional_models=%d, service=%d, platform=%d, linked=%d",
                len(exact_match_docs), len(additional_model_docs), len(service_docs),
                len(platform_docs), len(linked_docs))

    return context


def _create_filters(service_code: str, exclude_page_ids: Optional[List[str]]) -> dict:
    """Создает фильтры один раз"""
    if exclude_page_ids:
        return {
            "$and": [
                {"service_code": {"$eq": service_code}},
                {"page_id": {"$nin": exclude_page_ids}}
            ]
        }
    return {"service_code": {"$eq": service_code}}


def _prepare_search_queries(requirements_text: str) -> List[str]:
    """Подготавливает запросы для поиска с кешированием"""
    if not requirements_text.strip():
        return [""]  # Пустой запрос для фильтрации

    # Извлекаем ключевые запросы
    key_queries = extract_key_queries(requirements_text)

    if key_queries:
        logger.debug("[_prepare_search_queries] Using %d key queries", len(key_queries))
        return key_queries

    # Fallback: первые 10 слов
    fallback_query = " ".join(requirements_text.split()[:10])
    logger.warning("[_prepare_search_queries] -> Using fallback query: %s", fallback_query)
    return [fallback_query]


def batch_service_search(store_name: str, queries: List[str], filters: dict,
                         k_per_query: int, embeddings_model) -> List:
    """Батчевый поиск по одному хранилищу"""
    logger.debug("[batch_service_search] <- store='%s', queries='%s', filters='%s', k_per_query=%d",
                 store_name, queries, filters, k_per_query)

    store = get_vectorstore(store_name, embedding_model=embeddings_model)
    all_docs = []

    # ДОБАВИТЬ ЛОГИРОВАНИЕ ФИЛЬТРОВ ДЛЯ СРАВНЕНИЯ
    logger.debug("[batch_service_search] Store: %s, Filter: %s", store_name, filters)

    for query in queries:
        try:
            docs = store.similarity_search(query, k=k_per_query, filter=filters)
            all_docs.extend(docs)
            logger.debug("[batch_service_search] Store: %s, Query '%s' found %d docs",
                        store_name, query[:50], len(docs))
        except Exception as e:
            logger.error("[batch_service_search] Store: %s, Error searching '%s': %s",
                        store_name, query[:50], str(e))

    logger.debug("[batch_service_search] -> %d docs", len(all_docs))

    return all_docs


def batch_platform_search(queries: List[str], exclude_page_ids: Optional[List[str]],
                          k_per_query: int, embeddings_model, exclude_services: Optional[List[str]] = None) -> List:
    """
    Оптимизированный поиск по платформенным сервисам

    Args:
        queries: Список поисковых запросов
        exclude_page_ids: Исключаемые page_id
        k_per_query: Количество результатов на запрос
        embeddings_model: Модель эмбеддингов
        exclude_services: Список кодов сервисов для исключения из поиска
    """
    logger.debug("[batch_platform_search] <- %d queries, exclude pages = {%s}, exclude services = {%s}", len(queries), exclude_page_ids, exclude_services)

    platform_services = get_platform_services()
    if not platform_services:
        logger.warning("[batch_platform_search] No platform services found")
        return []

    # Фильтруем исключаемые сервисы (например, dataModel, в котором искали ранее)
    if exclude_services:
        exclude_set = set(exclude_services)
        platform_services = [svc for svc in platform_services if svc["code"] not in exclude_set]
        logger.debug("[batch_platform_search] Excluded services: %s", exclude_services)

    if not platform_services:
        logger.warning("[batch_platform_search] No platform services left after exclusions")
        return []

    platform_store = get_vectorstore("platform_context", embedding_model=embeddings_model)

    try:
        collection_data = platform_store.get()
        total_docs = len(collection_data.get('ids', []))
        logger.debug("[batch_platform_search] Platform collection contains %d documents", total_docs)

        # ОТЛАДКА: Показываем отфильтрованные сервисы
        if collection_data.get('metadatas'):
            sample_metadata = collection_data['metadatas'][:5]
            logger.debug("[batch_platform_search] Sample metadata: %s", sample_metadata)

            service_codes_in_data = set()
            for metadata in collection_data['metadatas'][:100]:
                if metadata and 'service_code' in metadata:
                    service_codes_in_data.add(metadata['service_code'])

            logger.debug("[batch_platform_search] Service codes in data: %s", sorted(service_codes_in_data))

        if total_docs == 0:
            logger.warning("[batch_platform_search] Platform collection is empty")
            return []

    except Exception as e:
        logger.error("[batch_platform_search] Error accessing platform collection: %s", str(e))
        return []

    all_platform_docs = []
    platform_codes = [svc["code"] for svc in platform_services]  # Уже отфильтрованный список
    logger.debug("[batch_platform_search] Searching in platform services: %s", platform_codes)

    exclude_set = set(exclude_page_ids) if exclude_page_ids else set()

    for query in queries:
        try:
            logger.debug("[batch_platform_search] Searching query: '%s'", query[:100])

            # ИСПРАВЛЕНИЕ: Ищем с простым фильтром, исключаем вручную
            docs = platform_store.similarity_search(
                query,
                k=(k_per_query * len(platform_services)) + len(exclude_set),
                filter={"service_code": {"$in": platform_codes}}  # Используем отфильтрованный список
            )

            # Фильтруем исключения вручную
            if exclude_set:
                filtered_docs = [
                    doc for doc in docs
                    if doc.metadata.get('page_id') not in exclude_set
                ]
                logger.debug("[_batch_platform_search] Filtered %d -> %d docs (excluded %d)",
                             len(docs), len(filtered_docs), len(docs) - len(filtered_docs))
                docs = filtered_docs

            # Ограничиваем до нужного количества
            docs = docs[:k_per_query * len(platform_services)]

            all_platform_docs.extend(docs)
            logger.debug("[batch_platform_search] Query '%s' found %d platform docs", query[:50], len(docs))

        except Exception as e:
            logger.error("[batch_platform_search] Error searching query '%s': %s", query[:50], str(e))

            # Fallback: Поиск вообще без фильтров
            try:
                logger.info("[batch_platform_search] Retrying query '%s' without filters", query[:50])
                docs = platform_store.similarity_search(query, k=k_per_query * 3)

                # Фильтруем вручную и по service_code, и по exclude_page_ids
                filtered_docs = []
                for doc in docs:
                    doc_service = doc.metadata.get('service_code')
                    doc_page_id = doc.metadata.get('page_id')

                    if (doc_service in platform_codes and
                            (not exclude_set or doc_page_id not in exclude_set)):
                        filtered_docs.append(doc)

                filtered_docs = filtered_docs[:k_per_query]
                all_platform_docs.extend(filtered_docs)
                logger.debug("[batch_platform_search] Fallback found %d docs", len(filtered_docs))

            except Exception as e2:
                logger.error("[batch_platform_search] Fallback also failed: %s", str(e2))

    logger.info("[batch_platform_search] -> %d platform docs found", len(all_platform_docs))
    return all_platform_docs


def _fast_deduplicate_documents(docs: List) -> List:
    """Быстрая дедупликация документов"""
    seen_composite_keys = set()
    unique_docs = []

    for doc in docs:
        page_id = doc.metadata.get('page_id')
        content_hash = hash(doc.page_content[:100])  # Используем первые 100 символов

        # Быстрая проверка через set
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

    # Обрезаем до максимальной длины
    truncated = context[:max_length]

    # Ищем последнюю точку, чтобы не обрезать посередине предложения
    last_period = truncated.rfind('.')
    if last_period > max_length * 0.8:  # Если точка не слишком далеко от конца
        truncated = truncated[:last_period + 1]

    logger.debug("[_smart_truncate_context] Truncated context from %d to %d chars", len(context), len(truncated))
    return truncated


def _extract_linked_context_optimized(exclude_page_ids: List[str]) -> List[str]:
    """
    Извлечение контекста по ссылкам ТОЛЬКО из неподтвержденных (цветных) фрагментов.
    Ссылки должны искаться только в неподтвержденных требованиях.
    """
    logger.info("[_extract_linked_context_optimized] <- Processing %d pages for links from unconfirmed fragments",
                 len(exclude_page_ids))

    if not exclude_page_ids:
        return []

    linked_docs = []
    max_linked_pages = 3
    max_pages = 5

    # Обрабатываем только первые max_pages страниц
    if len(exclude_page_ids) <= max_linked_pages:
        logger.warning("[_extract_linked_context_optimized] page ids truncated to %d items", max_pages)
    for page_id in exclude_page_ids[:max_pages]:
        try:
            content = get_page_content_by_id(page_id, clean_html=False)
            if not content:
                continue

            # Ищем ссылки ТОЛЬКО в неподтвержденных фрагментах
            linked_page_ids = _extract_links_from_unconfirmed_fragments(content, exclude_page_ids)
            logger.debug("[_extract_linked_context_optimized] Found %d links in unconfirmed fragments of page %s",
                         len(linked_page_ids), page_id)

            # Ограничиваем количество ссылок на страницу
            # TODO ограничивать нужно с учетом общего числа страниц, а не "в лоб". То есть учитывать "оставшиеся" токены.
            for linked_page_id in linked_page_ids[:2]:
                if len(linked_docs) >= max_linked_pages:
                    break

                linked_content = _get_approved_content_cached(linked_page_id)
                if linked_content and linked_content.strip():
                    linked_docs.append(linked_content)
                    logger.debug(
                        "[_extract_linked_context_optimized] Added approved content from linked page '%s' (%d chars)",
                        linked_page_id, len(linked_content))
                    logger.debug("[_extract_linked_context_optimized] linked page '%s' approved data = {%s}",
                                 linked_page_id, linked_content[:500] + "...")

            if len(linked_docs) >= max_linked_pages:
                break

        except Exception as e:
            logger.error("[_extract_linked_context_optimized] Error processing page_id=%s: %s", page_id, str(e))

    logger.info("[_extract_linked_context_optimized] -> Found %d linked documents from unconfirmed fragments",
                len(linked_docs))
    return linked_docs


def _extract_links_from_unconfirmed_fragments(html_content: str, exclude_page_ids: List[str]) -> List[str]:
    """
    НОВАЯ ФУНКЦИЯ: Извлекает ссылки ТОЛЬКО из неподтвержденных (цветных) фрагментов требований.
    Это правильная реализация согласно постановке задачи.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    found_page_ids = set()
    exclude_set = set(exclude_page_ids)

    # Счетчики для отладки
    colored_elements_count = 0
    links_found_count = 0

    # Ищем все элементы, которые могут содержать цветной (неподтвержденный) текст
    for element in soup.find_all(["p", "li", "span", "div", "td", "th"]):
        # Используем существующую функцию для определения цветного стиля
        if not has_colored_style(element):
            continue  # Пропускаем подтвержденные (черные) элементы

        colored_elements_count += 1

        # Ищем ссылки в этом цветном элементе
        element_links = _extract_confluence_links_from_element(element)

        for linked_page_id in element_links:
            if linked_page_id not in exclude_set and linked_page_id not in found_page_ids:
                found_page_ids.add(linked_page_id)
                links_found_count += 1
                logger.debug("[_extract_links_from_unconfirmed_fragments] Found link to page_id=%s in colored element",
                             linked_page_id)

    logger.debug("[_extract_links_from_unconfirmed_fragments] Processed: colored_elements=%d, unique_links_found=%d",
                 colored_elements_count, links_found_count)

    return list(found_page_ids)


def _extract_confluence_links_from_element(element) -> List[str]:
    """
    Извлекает все ссылки на страницы Confluence из конкретного элемента.
    Поддерживает разные форматы ссылок Confluence.
    (Эта функция уже была в коде и работает корректно)
    """
    import re
    page_ids = []

    # 1. Обычные HTML ссылки с pageId в URL
    for link in element.find_all('a', href=True):
        href = link['href']

        # Различные форматы ссылок Confluence
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
        # Ссылка через ri:page
        ri_page = ac_link.find('ri:page')
        if ri_page:
            page_id = ri_page.get('ri:content-id')
            if page_id:
                page_ids.append(page_id)
            else:
                # Если нет ri:content-id, можно попробовать найти по названию
                content_title = ri_page.get('ri:content-title')
                if content_title:
                    logger.debug("[_extract_confluence_links_from_element] Found link by title: %s (not resolved)",
                                 content_title)

    # 3. Прямые ri:page теги (иногда встречаются отдельно)
    for ri_page in element.find_all('ri:page'):
        page_id = ri_page.get('ri:content-id')
        if page_id:
            page_ids.append(page_id)

    return list(set(page_ids))  # Убираем дубликаты


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


# УДАЛЕНЫ СТАРЫЕ ФУНКЦИИ:
# - _extract_links_fast() (неправильная логика)
# Остались корректные функции, которые уже были в коде

def extract_confluence_links(html_content: str) -> List[str]:
    """Более точное извлечение ссылок на страницы Confluence"""
    soup = BeautifulSoup(html_content, 'html.parser')
    page_ids = set()

    # Ищем все типы ссылок Confluence
    for link in soup.find_all(['a', 'ac:link']):
        # Стандартные ссылки
        href = link.get('href', '')
        if 'pageId=' in href:
            match = re.search(r'pageId=(\d+)', href)
            if match:
                page_ids.add(match.group(1))

        # Внутренние ссылки Confluence
        ri_page = link.find('ri:page')
        if ri_page and ri_page.get('ri:content-title'):
            # Здесь можно добавить резолвинг названия в page_id через Confluence API
            pass

    return list(page_ids)


def _extract_json_from_llm_response(response: str) -> Optional[str]:
    """
    Извлекает JSON из ответа LLM, удаляя лишний текст и форматирование.
    """
    if not response:
        return None

    # Убираем markdown форматирование
    response = response.strip()
    response = response.strip("```json").strip("```").strip()

    # Ищем JSON блоки различными способами
    json_patterns = [
        # 1. JSON в markdown блоке
        r'```json\s*(\{.*?\})\s*```',
        # 2. JSON между фигурными скобками (многострочный)
        r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})',
        # 3. Простой поиск от первой { до последней }
        r'(\{.*\})',
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


_encoding = tiktoken.get_encoding("cl100k_base")  # Заменить на токенизатор DeepSeek, если доступен


def count_tokens(text: str) -> int:
    """Подсчитывает количество токенов в тексте с помощью токенизатора tiktoken."""
    if LLM_PROVIDER == "deepseek":
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")  # Уточните у DeepSeek
        return len(encoding.encode(text))
    else:
        try:
            return len(_encoding.encode(text))
        except Exception as e:
            logger.error("[count_tokens] Error counting tokens: %s", str(e))
            return len(text.split())  # Запасной вариант: подсчет слов


def analyze_text(text: str, prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    logger.info("[analyze_text] <- text length=%d, service_code=%s", len(text), service_code)
    if not service_code:
        service_code = resolve_service_code_by_user()
        logger.info("[analyze_text] Resolved service_code: %s", service_code)

    chain = build_chain(prompt_template)
    # ИЗМЕНЕНИЕ: передаем текст требований для семантического поиска
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
        template = prompt_template or open("page_prompt_template.txt", "r", encoding="utf-8").read().strip()
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

        logger.debug("[analyze_pages] Resolved requirements: %s", requirements_text)
        # ИЗМЕНЕНИЕ: передаем текст требований для семантического поиска
        context = build_context(service_code, requirements_text=requirements_text, exclude_page_ids=page_ids)

        context_tokens = count_tokens(context)
        if context_tokens > max_context_tokens:
            logging.warning("[analyze_pages] Context too large (%d tokens), limiting analysis to %d pages",
                            context_tokens, len(valid_page_ids))
            return [{"page_id": pid, "analysis": "Анализ невозможен: контекст слишком большой"} for pid in
                    valid_page_ids]

        # Остальная часть функции остается без изменений...
        full_prompt = PromptTemplate(
            input_variables=["requirement", "context"],
            template=template
        ).format(requirement=requirements_text, context=context)
        total_tokens = count_tokens(full_prompt)

        logger.debug("[analyze_pages] Tokens: requirements=%d, context=%d, template=%d, total=%d",
                     current_tokens, context_tokens, template_tokens, total_tokens)

        if total_tokens > max_tokens:
            logging.warning("[analyze_pages] Total tokens (%d) exceed max_tokens (%d)", total_tokens, max_tokens)
            return [{"page_id": pid, "analysis": "Анализ невозможен: превышен лимит токенов"} for pid in valid_page_ids]

        chain = build_chain(prompt_template)
        try:
            result = chain.run({"requirement": requirements_text, "context": context})

            # ДОБАВЛЯЕМ ОТЛАДКУ
            logger.info("[analyze_pages] Raw LLM response: %s", result[:1000])

            # УЛУЧШЕННАЯ ОЧИСТКА JSON
            cleaned_result = _extract_json_from_llm_response(result)

            if not cleaned_result:
                logger.error("[analyze_pages] No valid JSON found in LLM response: %s", result[:500])
                return [{"page_id": pid, "analysis": "Ошибка: LLM не вернул корректный JSON"} for pid in valid_page_ids]

            logger.info("[analyze_pages] Cleaned JSON: %s", cleaned_result[:500])

            try:
                parsed_result = json.loads(cleaned_result)
                logger.info("[analyze_pages] Parsed result keys: %s", list(parsed_result.keys()))
                logger.info("[analyze_pages] Expected page_ids: %s", valid_page_ids)
            except json.JSONDecodeError as json_err:
                logger.error("[analyze_pages] JSON decode error: %s\nCleaned result: %s",
                             str(json_err), cleaned_result[:500])
                # Fallback: возвращаем весь ответ как единый анализ
                return [{"page_id": valid_page_ids[0] if valid_page_ids else "unknown",
                         "analysis": result}]

            if not isinstance(parsed_result, dict):
                logger.error("[analyze_pages] Result is not a dictionary: %s", type(parsed_result))
                return [{"page_id": pid, "analysis": "Ошибка: неожиданный формат ответа LLM"} for pid in valid_page_ids]

            results = []
            for page_id in valid_page_ids:
                analysis = parsed_result.get(page_id, f"Анализ не найден для страницы {page_id}")
                results.append({"page_id": page_id, "analysis": analysis})
                # ДОПОЛНИТЕЛЬНАЯ ОТЛАДКА
                if page_id not in parsed_result:
                    logging.warning("[analyze_pages] Page ID %s not found in LLM response keys: %s",
                                    page_id, list(parsed_result.keys()))

            logger.info("[analyze_pages] -> Result count: %d", len(results))
            return results

        except Exception as e:
            if "token limit" in str(e).lower():
                logger.error("[analyze_pages] Token limit exceeded: %s", str(e))
                return [{"page_id": pid, "analysis": "Ошибка: превышен лимит токенов модели"} for pid in valid_page_ids]
            logger.error("[analyze_pages] Error in LLM chain: %s", str(e))
            raise
    except Exception as e:
        logging.exception("[analyze_pages] Ошибка в /analyze")
        raise


def analyze_with_templates(items: List[dict], prompt_template: Optional[str] = None,
                           service_code: Optional[str] = None):
    if not service_code:
        page_ids = [item["page_id"] for item in items]
        service_code = resolve_service_code_from_pages_or_user(page_ids)
        logger.info("[analyze_with_templates] Resolved service_code: %s", service_code)

    results = []
    for item in items:
        requirement_type = item["requirement_type"]
        page_id = item["page_id"]

        content = get_page_content_by_id(page_id, clean_html=True)
        template = get_template_by_type(requirement_type)
        if not content or not template:
            results.append({
                "page_id": page_id,
                "requirement_type": requirement_type,
                "analysis": "Ошибка: отсутствует содержимое страницы или шаблон",
                "formatting_issues": []
            })
            continue

        template_md = markdownify(template, heading_style="ATX")
        content_md = markdownify(content, heading_style="ATX")
        template_soup = BeautifulSoup(template_md, 'html.parser')
        content_soup = BeautifulSoup(content_md, 'html.parser')

        formatting_issues = []
        template_headers = [h.get_text().strip() for h in template_soup.find_all(['h1', 'h2', 'h3'])]
        content_headers = [h.get_text().strip() for h in content_soup.find_all(['h1', 'h2', 'h3'])]
        if set(template_headers) != set(content_headers):
            formatting_issues.append(
                f"Несоответствие заголовков: ожидаются {template_headers}, найдены {content_headers}")

        template_tables = template_soup.find_all('table')
        content_tables = content_soup.find_all('table')
        if len(template_tables) != len(content_tables):
            formatting_issues.append(
                f"Несоответствие количества таблиц: ожидается {len(template_tables)}, найдено {len(content_tables)}")

        chain = build_chain(prompt_template)
        context = build_context(service_code, exclude_page_ids=[page_id])
        try:
            result = chain.run({"requirement": content, "context": context})
            results.append({
                "page_id": page_id,
                "requirement_type": requirement_type,
                "analysis": result,
                "formatting_issues": formatting_issues
            })
        except Exception as e:
            if "token limit" in str(e).lower():
                results.append({
                    "page_id": page_id,
                    "requirement_type": requirement_type,
                    "analysis": "Ошибка: превышен лимит токенов модели",
                    "formatting_issues": formatting_issues
                })
            else:
                raise
    return results

def _search_data_models(entity_queries: List[str], service_code: str, exclude_page_ids: Optional[List[str]],
                        embeddings_model) -> List:
    """
    Специализированный поиск страниц с моделями данных

    Args:
        entity_queries: Запросы для поиска атрибутов сущностей
        service_code: Код сервиса для поиска в сервисном хранилище
        exclude_page_ids: Исключаемые страницы
        embeddings_model: Модель эмбеддингов
    """
    if not entity_queries:
        return []

    logger.debug("[_search_data_models] Searching with %d entity queries for service: %s",
                 len(entity_queries), service_code)

    # 1. ПОИСК В ПЛАТФОРМЕННОМ СЕРВИСЕ dataModel (всегда)
    platform_docs = search_in_platform_data_models(entity_queries, exclude_page_ids, embeddings_model)

    # 2. ПОИСК В КОНКРЕТНОМ СЕРВИСНОМ ХРАНИЛИЩЕ
    service_docs = search_in_service_data_models(entity_queries, service_code, exclude_page_ids, embeddings_model)

    all_docs = platform_docs + service_docs

    # 3. ДЕДУПЛИКАЦИЯ (могут быть пересечения)
    unique_docs = _fast_deduplicate_documents(all_docs)

    logger.info("[_search_data_models] -> Found %d unique data model documents", len(unique_docs))
    return unique_docs



def search_in_service_data_models(entity_queries: List[str], service_code: str, exclude_page_ids: Optional[List[str]],
                                  embeddings_model) -> List:
    """Поиск моделей данных в конкретном сервисном хранилище"""
    logger.debug("[search_in_service_data_models] <- %d entity queries: %s, service_code='%s', exclude_page_ids={%s}",
                 len(entity_queries), entity_queries, service_code, exclude_page_ids)

    try:
        service_store = get_vectorstore("service_pages", embedding_model=embeddings_model)

        # Фильтр для конкретного сервиса
        base_filter = {"service_code": {"$eq": service_code}}
        if exclude_page_ids:
            filters = {
                "$and": [
                    base_filter,
                    {"page_id": {"$nin": exclude_page_ids}}
                ]
            }
        else:
            filters = base_filter

        logger.debug("[search_in_service_data_models] filter: %s", filters)
        all_docs = []
        for query in entity_queries:
            try:
                # equery = re.sub(r'([\[\]])', r'\\\1', query)  # Экранируем квадратные скобки
                equery = re.sub(r'([\[\]])', r'', query)  # Убираем квадратные скобки
                logger.debug("[search_in_service_data_models] query: %s", equery)
                docs = service_store.similarity_search(equery, k=3, filter=filters)

                # Дополнительно фильтруем по признакам модели данных
                model_docs = [doc for doc in docs if _is_data_model_page(doc)]
                all_docs.extend(model_docs)

                logger.debug("[search_in_service_data_models] Query '%s' in service %s found %d model docs",
                             query[:50], service_code, len(model_docs))
            except Exception as e:
                logger.warning("[search_in_service_data_models] Error with query '%s': %s",
                               query[:50], str(e))

        logger.debug("[search_in_service_data_models] -> all_docs: %s", all_docs)
        return all_docs

    except Exception as e:
        logger.error("[search_in_service_data_models] Error: %s", str(e))
        return []


def search_in_platform_data_models(entity_queries: List[str], exclude_page_ids: Optional[List[str]],
                                   embeddings_model) -> List:
    """Поиск в платформенном сервисе dataModel"""
    logger.debug("[search_in_platform_data_models] <- exclude_page_ids={%s}, %d entity queries: %s",
                 exclude_page_ids, len(entity_queries), entity_queries)
    try:
        platform_store = get_vectorstore("platform_context", embedding_model=embeddings_model)

        # Фильтр для dataModel платформенного сервиса
        base_filter = {"service_code": {"$eq": "dataModel"}}
        if exclude_page_ids:
            filters = {
                "$and": [
                    base_filter,
                    {"page_id": {"$nin": exclude_page_ids}}
                ]
            }
        else:
            filters = base_filter

        logger.debug("[search_in_platform_data_models] filter: %s", filters)

        all_docs = []
        for query in entity_queries:
            try:
                # equery = re.sub(r'([\[\]])', r'\\\1', query) # Экранируем квадратные скобки
                equery = re.sub(r'([\[\]])', r'', query)  # Убираем квадратные скобки
                logger.debug("[search_in_platform_data_models] query: %s", equery)
                docs = platform_store.similarity_search(equery, k=3, filter=filters)
                all_docs.extend(docs)
                logger.debug("[search_in_platform_data_models] Query '%s' found %d docs",
                             query[:50], len(docs))
            except Exception as e:
                logger.warning("[search_in_platform_data_models] Error with query '%s': %s",
                               query[:100], str(e))

        logger.debug("[search_in_platform_data_models] -> all_docs: %s", all_docs)
        return all_docs

    except Exception as e:
        logger.error("[search_in_platform_data_models] Error: %s", str(e))
        return []


def _is_data_model_page(doc) -> bool:
    """
    Определяет, является ли страница описанием модели данных
    Использует только НАДЕЖНЫЕ признаки
    """
    content = doc.page_content.lower()

    # ГЛАВНЫЙ признак - наличие фразы "атрибутный состав сущности"
    has_attribute_composition = 'атрибутный состав сущности' in content

    if has_attribute_composition:
        logger.debug("[_is_data_model_page] Document '%s' identified as data model (has 'атрибутный состав сущности')",
                     doc.metadata.get('title', '')[:50])
        return True

    return False