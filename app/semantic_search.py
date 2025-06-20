# app/semantic_search.py

import logging
import re
from typing import List, Set, Optional
from langchain_core.prompts import PromptTemplate
from langchain.chains.llm import LLMChain

from app.embedding_store import get_vectorstore
from app.llm_interface import get_llm

logger = logging.getLogger(__name__)  # Лучше использовать __name__ для именованных логгеров


def extract_key_queries(requirements_text: str) -> List[str]:
    """
    Извлекает ключевые запросы + специальные запросы для сущностей через LLM
    """
    logger.info("[extract_key_queries] <- text length: %d chars", len(requirements_text))

    if not requirements_text.strip():
        return []

    # 1. СНАЧАЛА извлекаем специальные запросы для сущностей
    entity_queries = extract_entity_attribute_queries(requirements_text)

    # 2. ЗАТЕМ извлекаем обычные ключевые запросы с помощью LLM
    regular_queries = _extract_regular_key_queries_with_llm(requirements_text)

    # 3. Объединяем
    # приоритет - запросам сущностей
    # all_queries = entity_queries + regular_queries
    # LLM лучше вычленяет сущности, даже если не соблюдается оформление "Сущность.атрибут",
    # а по строгим названиям сущностей к этому времени уже поиск произведен.
    all_queries = regular_queries + entity_queries

    # 4. Ограничиваем общее количество (приоритет у entity_queries)
    logger.info("[extract_key_queries] -> queries: %s", all_queries[:12])
    return all_queries[:12]


def _extract_regular_key_queries_with_llm(requirements_text: str) -> List[str]:
    """
    Извлекает обычные ключевые запросы с помощью LLM
    (переименовал из extract_regular_key_queries для ясности)
    """
    # Ограничиваем длину входного текста для анализа
    max_input_length = 2000
    if len(requirements_text) > max_input_length:
        requirements_text = requirements_text[:max_input_length] + "..."

    prompt_template = """
Проанализируй текст требований и извлеки ключевые запросы для поиска связанных требований.

Текст требований:
{requirements}

Извлеки:
1. Технические термины и компоненты (API, базы данных, сервисы)
2. Бизнес-сущности (клиенты, продукты, операции)
3. Процессы и функции (авторизация, валидация, обработка)
4. Форматы и стандарты (JSON, XML, протоколы)

Верни 5-6 наиболее важных ключевых запросов, каждый на новой строке:
"""

    try:
        llm = get_llm()
        prompt = PromptTemplate(
            input_variables=["requirements"],
            template=prompt_template
        )
        chain = LLMChain(llm=llm, prompt=prompt)

        result = chain.run(requirements=requirements_text)
        logger.debug("[_extract_regular_key_queries_with_llm] Raw LLM result: %s", str(result))

        # Парсим результат (существующая логика из вашего кода)
        queries = []
        for line in result.split('\n'):
            line = line.strip()
            line = re.sub(r'^\d+\.\s*[-+*]*', '', line)
            line = re.sub(r'^\[\[', '[', line)
            line = re.sub(r'[\]+*-]+$', '', line)
            if line and len(line) > 2:
                queries.append(line)

        queries = queries[:6]  # Ограничиваем для LLM запросов

        logger.debug("[_extract_regular_key_queries_with_llm] extracted LLM queries = {%s}", queries)
        logger.info("[_extract_regular_key_queries_with_llm] -> extracted %d LLM queries", len(queries))

        return queries

    except Exception as e:
        logging.error("[_extract_regular_key_queries_with_llm] Error extracting queries: %s", str(e))
        return extract_simple_keywords(requirements_text)


def extract_entity_attribute_queries(requirements_text: str) -> List[str]:
    """
    Формирует запросы для поиска в хранилище моделей данных сущностей и их атрибутов
    на основе парсинга из текста "Сущность.Атрибут" (в разных вариациях и ограничителях).
    """
    logger.info("[extract_entity_attribute_queries] <- text length: %d chars", len(requirements_text))

    entity_queries = []

    # Извлекаем все цепочки сущность.атрибут
    entity_chains = _extract_entity_chains(requirements_text)

    for chain in entity_chains:
        entities = chain['entities']
        final_attribute = chain['final_attribute']

        # Создаем запросы для каждой сущности в цепочке
        for entity_name in entities:
            if len(entity_name.split()) <= 5:  # Ограничение: не более 5 слов
                # Создаем специализированные запросы для поиска модели данных
                queries = [
                    f'Атрибутный состав сущности {entity_name}',
                    f'модель данных {entity_name}',
                    f'{entity_name} атрибут',
                    f'Наименование поля',
                    f'{entity_name} реквизит'
                ]

                # Если есть финальный атрибут, добавляем его в запросы
                if final_attribute:
                    queries.extend([
                        f'модель данных {entity_name} {final_attribute}',
                        f'{entity_name} атрибут {final_attribute}',
                        f'Наименование поля {final_attribute}',
                        f'{entity_name} реквизит {final_attribute}'
                    ])

                entity_queries.extend(queries)
                logger.debug("[extract_entity_attribute_queries] Found entity: '%s', final_attribute: '%s'",
                             entity_name, final_attribute)

    # Удаляем дубликаты
    unique_queries = list(dict.fromkeys(entity_queries))

    logger.info("[extract_entity_attribute_queries] -> extracted %d entity queries from %d chains",
                len(unique_queries), len(entity_chains))

    return unique_queries


def _extract_entity_chains(text: str) -> List[dict]:
    """
    Извлекает цепочки сущность.атрибут на основе правил оформления
    Извлечение сущностей и атрибутов

    Поддержка кавычек: "Клиент Банка".<идентификатор записи>
    Поддержка апострофов: 'Заявка на выпуск'.<статус>
    Поддержка квадратных скобок: [[КК_ВК] Заявка на выпуск карты].<Статус документа>
    Поддержка простых названий: Сущность10.<атрибут 1>
    Поддержка иерархических ссылок: [Сущ1].<[Сущ2]>.<атрибут>
    """
    chains = []

    # ИСПРАВЛЕНО: Правильный паттерн для квадратных скобок БЕЗ точек внутри
    chain_patterns = [
        # 1. Цепочки и иерархические ссылки
        r'\[([\[\]\s\w]{1,50})\]\.<\[([\[\]\s\w]{1,50})\]>\.<([^>]{1,50})>',  # [Сущ1].<[Сущ2]>.<атр>
        r'\[([\[\]\s\w]{1,50})\]\.<\[([\[\]\s\w]{1,50})\]>\.\"([^\"]{1,50})\"',  # [Сущ1].<[Сущ2]>."атр"

        r'"([^"]{1,50})"\."([^"]{1,50})"\.<([^>]{1,50})>',
        r'"([^"]{1,50})"\."([^"]{1,50})"\."([^"]{1,50})"',

        r"'([^']{1,50})'\.'([^']{1,50})'\.<([^>]{1,50})>",

        # 2. ИСПРАВЛЕНО: Одиночные ссылки в квадратных скобках БЕЗ точек
        r'\[([\[\]\s\w]{1,50})\]\.<([^>]{1,50})>',  # [Название без точек].<атрибут>
        r'\[([\[\]\s\w]{1,50})\]\."([^"]{1,50})"',  # [Название]."атрибут"
        r'\[([\[\]\s\w]{1,50})\]\.\'([^\']{1,50})\'',  # [Название].'атрибут'

        # 3. Кавычки
        r'"([^"]{1,50})"\.<([^>]{1,50})>',
        r'"([^"]{1,50})"\."([^"]{1,50})"',

        r"'([^']{1,50})'\.<([^>]{1,50})>",
        r"'([^']{1,50})'\.'([^']{1,50})'",

        # 4. Простые названия (в последнюю очередь)
        r'\b([А-Яа-яA-Za-z][А-Яа-яA-Za-z0-9_]{2,49})\.<([^>]{1,50})>',
        r'\b([А-Яа-яA-Za-z][А-Яа-яA-Za-z0-9_]{2,49})\."([^"]{1,50})"',
    ]

    for pattern in chain_patterns:
        matches = re.finditer(pattern, text, re.UNICODE)

        for match in matches:
            # Получаем все группы (исключаем None)
            groups = [g.strip() for g in match.groups() if g and g.strip()]

            if len(groups) >= 2:
                # Все группы кроме последней - сущности
                entities = groups[:-1]
                # Последняя группа - атрибут
                final_attribute = groups[-1]

                # Фильтрация простых названий
                filtered_entities = []
                for entity in entities:
                    # Проверяем, что сущность не является стоп-словом
                    if (len(entity.split()) <= 5 and
                            len(entity) >= 3 and
                            entity.lower() not in ['или', 'для', 'при', 'как', 'что', 'это', 'проверить', 'значение']):
                        filtered_entities.append(entity)

                if filtered_entities and final_attribute:
                    # Проверяем, что такая цепочка еще не найдена
                    chain_key = (tuple(filtered_entities), final_attribute)
                    existing_chain = any(
                        (tuple(chain['entities']), chain['final_attribute']) == chain_key
                        for chain in chains
                    )

                    if not existing_chain:
                        chains.append({
                            'entities': filtered_entities,
                            'final_attribute': final_attribute,
                            'full_match': match.group(0)
                        })

                        logger.debug("[_extract_entity_chains] Pattern matched: entities=%s, attribute='%s'",
                                     filtered_entities, final_attribute)

    return chains


def extract_simple_keywords(text: str) -> List[str]:
    """
    Запасной метод: простое извлечение ключевых слов без LLM
    """
    logger.info("[extract_simple_keywords] Fallback keyword extraction")

    # Технические термины, которые часто встречаются в требованиях
    technical_terms = {
        'api', 'json', 'xml', 'rest', 'soap', 'http', 'https',
        'авторизация', 'аутентификация', 'токен', 'jwt',
        'сущность', 'процесс', 'алгоритм', 'таблица',
        'клиент', 'пользователь', 'продукт', 'услуга',
        'справочник', 'каталог', 'реестр',
        'обработка', 'валидация', 'проверка',
        'уведомление', 'нотификация', 'сообщение',
        'форма', 'экран', 'интерфейс',
        'отчет', 'печать', 'документ'
    }

    text_lower = text.lower()
    found_terms = []

    for term in technical_terms:
        if term in text_lower:
            found_terms.append(term)

    # Добавляем слова длиннее 4 символов, встречающиеся часто
    words = re.findall(r'\b[а-яё]{4,}\b', text_lower)
    word_freq = {}
    for word in words:
        word_freq[word] = word_freq.get(word, 0) + 1

    # Берем часто встречающиеся слова
    frequent_words = [word for word, freq in word_freq.items() if freq >= 2]
    found_terms.extend(frequent_words[:5])

    return found_terms[:8]


def deduplicate_documents(docs: List) -> List:
    """
    Удаляет дублирующиеся документы на основе page_id и содержимого
    """
    seen_pages = set()
    seen_content = set()
    unique_docs = []

    for doc in docs:
        page_id = doc.metadata.get('page_id')
        content_hash = hash(doc.page_content[:200])  # Хеш первых 200 символов

        if page_id not in seen_pages and content_hash not in seen_content:
            seen_pages.add(page_id)
            seen_content.add(content_hash)
            unique_docs.append(doc)

    logger.debug("[deduplicate_documents] Filtered %d -> %d documents", len(docs), len(unique_docs))
    return unique_docs


def search_by_entity_title(entity_names: List[str], service_code: str, exclude_page_ids: Optional[List[str]],
                           embeddings_model) -> List:
    """
    Поиск в хранилищах (платформенном и сервисном) страниц с точным совпадением title с именем сущности.
    Это самый точный способ найти модель данных сущности.
    """
    logger.debug("[search_by_entity_title] <- Searching by exact title match for entities: %s", entity_names)

    if not entity_names:
        return []

    found_docs = []

    # 1. ПОИСК В ПЛАТФОРМЕННОМ dataModel
    platform_docs = search_by_title_in_platform(entity_names, exclude_page_ids, embeddings_model)
    found_docs.extend(platform_docs)

    # 2. ПОИСК В СЕРВИСНОМ ХРАНИЛИЩЕ
    service_docs = search_by_title_in_service(entity_names, service_code, exclude_page_ids, embeddings_model)
    found_docs.extend(service_docs)

    logger.info("[search_by_entity_title] -> Found %d documents by exact title match", len(found_docs))
    return found_docs


def search_by_title_in_platform(entity_names: List[str], exclude_page_ids: Optional[List[str]],
                                embeddings_model) -> List:
    """Поиск по всем title в платформенном dataModel сервисе"""
    logger.debug("[search_by_title_in_platform] <- Search by title for entities: %s", entity_names)

    if not entity_names:
        return []

    try:
        platform_store = get_vectorstore("platform_context", embedding_model=embeddings_model)

        # Очищаем названия сущностей
        cleaned_entity_names = [name.strip() for name in entity_names if name.strip()]

        if not cleaned_entity_names:
            return []

        # Ищем сразу по всем сущностям одним запросом
        # Строим один оптимальный фильтр
        filters = {
            "$and": [
                {"service_code": {"$eq": "dataModel"}},
                {"title": {"$in": cleaned_entity_names}}  # Сразу фильтруем по нужным title
            ]
        }

        # Добавляем исключение page_ids если нужно
        if exclude_page_ids:
            filters["$and"].append({"page_id": {"$nin": exclude_page_ids}})

        logger.debug("[search_by_title_in_platform] Searching optimized filter = %s, query = ''", filters)

        # Один запрос для всех сущностей
        docs = platform_store.similarity_search(
            query="",  # Пустой запрос, полагаемся только на фильтры
            k=len(cleaned_entity_names) * 5,  # k = количество сущностей * возможные дубли
            filter=filters
        )

        logger.debug("[search_by_title_in_platform] Found %d docs for entities: %s",
                     len(docs), cleaned_entity_names)

        # Логируем какие именно сущности найдены
        found_titles = set(doc.metadata.get('title', '') for doc in docs)
        logger.info("[search_by_title_in_platform] -> Found documents for entities: %s", sorted(found_titles))

        return docs

    except Exception as e:
        logger.error("[search_by_title_in_platform] Error: %s", str(e))
        return []


def search_by_title_in_service(entity_names: List[str], service_code: str, exclude_page_ids: Optional[List[str]],
                               embeddings_model) -> List:
    """Поиск по всем title в сервисном хранилище"""
    logger.debug("[search_by_title_in_service] <- Search by title for entities %s, service code = %s",
                 entity_names, service_code)

    if not entity_names:
        return []

    try:
        service_store = get_vectorstore("service_pages", embedding_model=embeddings_model)

        # Очищаем названия сущностей
        cleaned_entity_names = [name.strip() for name in entity_names if name.strip()]

        if not cleaned_entity_names:
            return []

        # ИСПРАВЛЕНО: Ищем сразу по всем сущностям одним запросом
        # Строим один оптимальный фильтр
        base_filter = {
            "$and": [
                {"service_code": {"$eq": "dataModel"}},
                {"title": {"$in": cleaned_entity_names}}  # Сразу фильтруем по нужным title
            ]
        }

        # Добавляем исключение page_ids если нужно
        if exclude_page_ids:
            base_filter["$and"].append({"page_id": {"$nin": exclude_page_ids}})

        logger.debug("[search_by_title_in_service] Searching optimized filter = %s, query = ''", base_filter)

        # Один запрос для всех сущностей
        docs = service_store.similarity_search(
            query="",  # Пустой запрос, полагаемся только на фильтры
            k=len(cleaned_entity_names) * 3,  # k = количество сущностей * возможные дубли
            filter=base_filter
        )

        logger.debug("[search_by_title_in_service] Found %d docs for entities %s",
                     len(docs), cleaned_entity_names, service_code)

        # Логируем какие именно сущности найдены
        found_titles = set(doc.metadata.get('title', '') for doc in docs)
        logger.info("[search_by_title_in_service] -> Found documents for entities %s in service %s",
                    sorted(found_titles), service_code)

        return docs

    except Exception as e:
        logger.error("[search_by_title_in_service] Error: %s", str(e))
        return []


def extract_entity_names_from_requirements(requirements_text: str) -> List[str]:
    """
    Извлекает названия сущностей из текста требований для точного поиска по title
    """
    logger.debug("[extract_entity_names_from_requirements] <- %s" % requirements_text)
    entity_names = []

    # Используем новый подход с цепочками
    entity_chains = _extract_entity_chains(requirements_text)

    for chain in entity_chains:
        for entity_name in chain['entities']:
            if entity_name not in entity_names and len(entity_name.split()) <= 5:
                entity_names.append(entity_name)

    logger.debug("[extract_entity_names_from_requirements] -> entity names: %s", entity_names)
    return entity_names