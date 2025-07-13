# app/services/context_builder.py

from typing import Optional, List
from langchain_core.documents import Document  # ДОБАВЛЯЕМ ИМПОРТ
from app.config import UNIFIED_STORAGE_NAME
from app.confluence_loader import get_page_content_by_id
from app.embedding_store import get_vectorstore
from app.llm_interface import get_embeddings_model
from app.rag_pipeline import logger, _extract_links_from_unconfirmed_fragments, \
    _get_approved_content_cached, count_tokens
from app.semantic_search import extract_entity_names_from_requirements, unified_search_by_entity_title, \
    extract_entity_attribute_queries, extract_key_queries
from app.service_registry import get_platform_services
from app.services.template_type_analysis import get_template_name_by_type


def build_context(service_code: str, requirements_text: str = "", exclude_page_ids: Optional[List[str]] = None):
    """
    Формирование контекста с использованием единого хранилища.
    ИЗМЕНЕНО: Теперь добавляет заголовки к документам в контексте.

    Args:
        service_code: Код сервиса
        requirements_text: Текст анализируемых требований для семантического поиска
        exclude_page_ids: Список ID страниц, исключаемых из контекста

    Returns:
        Строковый контекст с заголовками документов
    """
    logger.info("[build_context] <- service_code=%s, requirements_length=%d, exclude_pages=%d",
                service_code, len(requirements_text), len(exclude_page_ids or []))

    embeddings_model = get_embeddings_model()

    #
    # 1. Извлекаем названия сущностей для точного поиска по title
    #
    entity_names = extract_entity_names_from_requirements(requirements_text)
    logger.debug("[build_context] step1 passed: entity names for title search = '%s'", entity_names)

    #
    # 2. Точный поиск документов по названиям сущностей (приоритет #1)
    #
    exact_match_docs = unified_search_by_entity_title(entity_names, service_code, exclude_page_ids, embeddings_model)
    logger.debug("[build_context] step2 passed: exact matched docs = %d", len(exact_match_docs))

    #
    # 3. Извлекаем ключевые запросы из текста требований
    #
    search_queries = _prepare_search_queries(requirements_text)
    entity_queries = extract_entity_attribute_queries(requirements_text)
    regular_queries = [q for q in search_queries if q not in entity_queries]
    logger.debug("[build_context] step3 passed: regular queries = '%s'", regular_queries)

    #
    # 4. Поиск по требованиям текущего сервиса
    #
    service_docs = unified_service_search(
        queries=regular_queries,
        service_code=service_code,
        exclude_page_ids=exclude_page_ids,
        k_per_query=3,
        embeddings_model=embeddings_model
    )
    logger.debug("[build_context] step4 passed: found %d service docs.", len(service_docs))

    #
    # 5. Поиск по платформенным требованиям (кроме dataModel)
    #
    platform_docs = unified_platform_search(
        queries=regular_queries,
        exclude_page_ids=exclude_page_ids,
        k_per_query=2,
        embeddings_model=embeddings_model,
        exclude_services=["dataModel"]
    )
    logger.debug("[build_context] step5 passed: found %d platform docs.", len(platform_docs))

    #
    # 6. Контекст из ссылок неподтвержденных требований
    #
    linked_docs = _extract_linked_context_optimized(exclude_page_ids) if exclude_page_ids else []
    logger.debug("[build_context] step6 passed: found %d linked docs.", len(linked_docs))

    #
    # 7. Объединяем все документы (приоритет у точных совпадений)
    #
    all_docs = exact_match_docs + service_docs + platform_docs + linked_docs
    unique_docs = _fast_deduplicate_documents(all_docs)
    logger.debug("[build_context] step7 passed: total %d unique docs.", len(unique_docs))

    #
    # 8. ИЗМЕНЕНО: Формируем контекст с названиями шаблонов вместо кодов
    #
    context_parts = []
    for doc in unique_docs:
        # Добавляем заголовок документа
        title = doc.metadata.get('title', 'Без названия')
        requirement_type_code = doc.metadata.get('requirement_type', 'unknown')

        # ИЗМЕНЕНИЕ: Получаем человекочитаемое название типа шаблона
        requirement_type_name = get_template_name_by_type(requirement_type_code)

        header = f"---\ntitle: {title}\ntype: {requirement_type_name}\n---\n"
        context_parts.append(header + doc.page_content)

        logger.debug("[build_context] Added doc: title='%s', type_code='%s', type_name='%s'",
                     title, requirement_type_code, requirement_type_name)

    context = "\n\n".join(context_parts)
    context = _smart_truncate_context(context, max_length=16000)

    logger.debug("[build_context] step8 passed: context=\n'%s'", context)
    logger.info("[build_context] -> Context with template names, length = %d", len(context))
    return context


def build_context_optimized(service_code: str, requirements_text: str = "",
                            exclude_page_ids: Optional[List[str]] = None):
    """
    ОПТИМИЗИРОВАННАЯ версия с умным ограничением контекста
    """
    logger.info("[build_context_optimized] <- service_code=%s, requirements_length=%d, exclude_pages=%d",
                service_code, len(requirements_text), len(exclude_page_ids or []))

    embeddings_model = get_embeddings_model()

    # Настройки ограничений
    MAX_DOCS_TOTAL = 15  # Максимум документов в контексте
    MAX_TOKENS_TOTAL = 14000  # Резерв для обрезки

    context_docs = []
    current_tokens = 0

    #
    # 1. ТОЧНЫЕ СОВПАДЕНИЯ (высший приоритет)
    #
    entity_names = extract_entity_names_from_requirements(requirements_text)
    if entity_names and len(context_docs) < MAX_DOCS_TOTAL:
        exact_docs = unified_search_by_entity_title(
            entity_names, service_code, exclude_page_ids, embeddings_model
        )

        # РАННЕЕ ОГРАНИЧЕНИЕ
        exact_docs = exact_docs[:min(8, MAX_DOCS_TOTAL - len(context_docs))]

        for doc in exact_docs:
            tokens = count_tokens_with_header(doc)
            if current_tokens + tokens < MAX_TOKENS_TOTAL:
                context_docs.append(doc)
                current_tokens += tokens
            else:
                logger.info("[build_context_optimized] Early stop: token limit reached at exact matches")
                break
    logger.debug("[build_context_optimized] step1 passed: exact matched docs = %d", len(context_docs))

    #
    # 2. СЕРВИСНЫЕ ДОКУМЕНТЫ (если еще есть место)
    #
    if len(context_docs) < MAX_DOCS_TOTAL and current_tokens < MAX_TOKENS_TOTAL:
        search_queries = _prepare_search_queries(requirements_text)
        regular_queries = [q for q in search_queries if q not in extract_entity_attribute_queries(requirements_text)]

        service_docs = unified_service_search(
            queries=regular_queries,
            service_code=service_code,
            exclude_page_ids=exclude_page_ids,
            k_per_query=2,  # УМЕНЬШАЕМ, так как ограничиваем рано
            embeddings_model=embeddings_model
        )

        # Дедупликация с уже найденными
        service_docs = _deduplicate_with_existing(service_docs, context_docs)
        service_docs = service_docs[:min(5, MAX_DOCS_TOTAL - len(context_docs))]

        for doc in service_docs:
            tokens = count_tokens_with_header(doc)
            if current_tokens + tokens < MAX_TOKENS_TOTAL and len(context_docs) < MAX_DOCS_TOTAL:
                context_docs.append(doc)
                current_tokens += tokens
            else:
                logger.info("[build_context_optimized] Early stop: limit reached at service docs")
                break
    logger.debug("[build_context_optimized] step2 passed: total docs (including service's) = %d", len(context_docs))

    #
    # 3. ПЛАТФОРМЕННЫЕ ДОКУМЕНТЫ (если еще есть место)
    #
    if len(context_docs) < MAX_DOCS_TOTAL and current_tokens < MAX_TOKENS_TOTAL:
        platform_docs = unified_platform_search(
            queries=regular_queries,
            exclude_page_ids=exclude_page_ids,
            k_per_query=1,  # УМЕНЬШАЕМ
            embeddings_model=embeddings_model,
            exclude_services=["dataModel"]
        )

        platform_docs = _deduplicate_with_existing(platform_docs, context_docs)

        for doc in platform_docs:
            tokens = count_tokens_with_header(doc)
            if current_tokens + tokens < MAX_TOKENS_TOTAL and len(context_docs) < MAX_DOCS_TOTAL:
                context_docs.append(doc)
                current_tokens += tokens
            else:
                logger.info("[build_context_optimized] Early stop: limit reached at platform docs")
                break
    logger.debug("[build_context_optimized] step3 passed: total docs (including platform's) = %d", len(context_docs))

    #
    # 4. СВЯЗАННЫЕ ДОКУМЕНТЫ (только если совсем мало контекста)
    #
    if len(context_docs) < 5 and exclude_page_ids:  # Только если мало нашли
        linked_docs = _extract_linked_context_optimized(exclude_page_ids)
        linked_docs = _deduplicate_with_existing(linked_docs, context_docs)

        for doc in linked_docs:
            tokens = count_tokens_with_header(doc)
            if current_tokens + tokens < MAX_TOKENS_TOTAL and len(context_docs) < MAX_DOCS_TOTAL:
                context_docs.append(doc)
                current_tokens += tokens
            else:
                break
    logger.debug("[build_context_optimized] step4 passed: total docs (including linked) = %d", len(context_docs))

    # Формируем финальный контекст
    context = _build_final_context(context_docs)

    logger.info("[build_context_optimized] -> Optimized context: %d docs, %d tokens",
                len(context_docs), current_tokens)
    return context


def _build_final_context(context_docs: List[Document]) -> str:
    """
    Формирует финальный контекст из списка документов с заголовками.

    Args:
        context_docs: Список документов для включения в контекст

    Returns:
        Строковый контекст с заголовками документов
    """
    logger.debug("[build_final_context] <- got %d docs", len(context_docs))
    from app.services.template_type_analysis import get_template_name_by_type

    if not context_docs:
        return ""

    context_parts = []

    for doc in context_docs:
        # Добавляем заголовок документа
        title = doc.metadata.get('title', 'Без названия')
        requirement_type_code = doc.metadata.get('requirement_type', 'unknown')

        # Получаем человекочитаемое название типа шаблона
        requirement_type_name = get_template_name_by_type(requirement_type_code)

        header = f"---\ntitle: {title}\ntype: {requirement_type_name}\n---\n"
        context_parts.append(header + doc.page_content)

        logger.debug("[_build_final_context] Added doc: title='%s', type_code='%s', type_name='%s'",
                     title, requirement_type_code, requirement_type_name)

    context = "\n\n".join(context_parts)

    logger.debug("[_build_final_context] -> Built context %d chars = \n'%s'",
                 len(context), context)

    return context

def count_tokens_with_header(doc: Document) -> int:
    """Подсчет токенов с учетом заголовка"""
    title = doc.metadata.get('title', 'Без названия')
    requirement_type = doc.metadata.get('requirement_type', 'unknown')
    header = f"---\ntitle: {title}\ntype: {requirement_type}\n---\n"

    return count_tokens(header + doc.page_content)


def _deduplicate_with_existing(new_docs: List[Document], existing_docs: List[Document]) -> List[Document]:
    """Удаляет из new_docs те, что уже есть в existing_docs"""
    existing_page_ids = {doc.metadata.get('page_id') for doc in existing_docs}
    return [doc for doc in new_docs if doc.metadata.get('page_id') not in existing_page_ids]


def _extract_linked_context_optimized(exclude_page_ids: List[str]) -> List[Document]:
    """
    ИЗМЕНЕНО: Теперь возвращает список Document объектов вместо строк.
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
            logger.debug("[_extract_linked_context_optimized] Found %d links in unconfirmed fragments for page '%s'",
                         len(linked_page_ids), page_id)

            for linked_page_id in linked_page_ids[:2]:
                if len(linked_docs) >= max_linked_pages:
                    break

                linked_content = _get_approved_content_cached(linked_page_id)
                if linked_content and linked_content.strip():
                    # ИЗМЕНЕНО: Создаем Document объект
                    from app.confluence_loader import get_page_title_by_id
                    linked_title = get_page_title_by_id(linked_page_id) or f"Страница {linked_page_id}"

                    doc = Document(
                        page_content=linked_content,
                        metadata={
                            'page_id': linked_page_id,
                            'title': linked_title,
                            'requirement_type': 'linked',
                            'source': 'linked_reference'
                        }
                    )
                    linked_docs.append(doc)
                    logger.debug("[_extract_linked_context_optimized] Added content from linked page '%s'",
                                 linked_page_id)

            if len(linked_docs) >= max_linked_pages:
                break

        except Exception as e:
            logger.error("[_extract_linked_context_optimized] Error processing page_id=%s: %s", page_id, str(e))

    logger.info("[_extract_linked_context_optimized] -> Found %d linked documents", len(linked_docs))
    return linked_docs


def unified_service_search(queries: List[str], service_code: str, exclude_page_ids: Optional[List[str]],
                           k_per_query: int, embeddings_model) -> List[Document]:
    """
    ИЗМЕНЕНО: Теперь возвращает список Document объектов вместо строк.
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
                            k_per_query: int, embeddings_model, exclude_services: Optional[List[str]] = None) -> List[
    Document]:
    """
    ИЗМЕНЕНО: Теперь возвращает список Document объектов вместо строк.
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


def _fast_deduplicate_documents(docs: List[Document]) -> List[Document]:
    """
    ИЗМЕНЕНО: Теперь принимает и возвращает Document объекты.
    Быстрая дедупликация документов
    """
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


def _prepare_search_queries(requirements_text: str) -> List[str]:
    """Формирует запросы для поиска с помощью LLM"""
    if not requirements_text.strip():
        return [""]

    # Извлекаем ключевые запросы с помощью LLM
    key_queries = extract_key_queries(requirements_text)

    if key_queries:
        logger.debug("[_prepare_search_queries] -> Using %d key queries", len(key_queries))
        return key_queries

    # Fallback: если ничего не нашли - берем первые 10 слов
    fallback_query = " ".join(requirements_text.split()[:10])
    logger.warning("[_prepare_search_queries] -> Using fallback query: %s", fallback_query)
    return [fallback_query]


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