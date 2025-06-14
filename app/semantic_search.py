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
    УЛУЧШЕННАЯ версия: Извлекает ключевые запросы + специальные запросы для сущностей
    """
    logger.info("[extract_key_queries] <- text length: %d chars", len(requirements_text))

    if not requirements_text.strip():
        return []

    # 1. СНАЧАЛА извлекаем специальные запросы для сущностей
    entity_queries = extract_entity_attribute_queries(requirements_text)

    # 2. ЗАТЕМ извлекаем обычные ключевые запросы с помощью LLM
    regular_queries = _extract_regular_key_queries_with_llm(requirements_text)

    # 3. Объединяем, приоритет - запросам сущностей
    all_queries = entity_queries + regular_queries

    # 4. Ограничиваем общее количество (приоритет у entity_queries)
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

        logger.info("[_extract_regular_key_queries_with_llm] -> extracted %d LLM queries", len(queries))
        return queries

    except Exception as e:
        logging.error("[_extract_regular_key_queries_with_llm] Error extracting queries: %s", str(e))
        return extract_simple_keywords(requirements_text)


def extract_entity_attribute_queries(requirements_text: str) -> List[str]:
    """
    Извлекает специальные запросы для поиска моделей данных сущностей
    на основе правил оформления: Сущность.Атрибут
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
    """
    chains = []

    # ДОБАВЛЕНО: Паттерн для одного элемента (сущность или атрибут)
    element_patterns = [
        r'"([^"]{1,50})"',  # Двойные кавычки
        r"'([^']{1,50})'",  # Одинарные кавычки
        r'<([^>]{1,50})>',  # Треугольные скобки
        r'\[([^\]]{1,50})\]',  # Квадратные скобки
        r'\b([А-Яа-яA-Za-z][А-Яа-яA-Za-z0-9_]{0,49})\b'  # Простые названия без кавычек
    ]

    # Объединяем все паттерны
    combined_pattern = '|'.join(f'({pattern})' for pattern in element_patterns)

    # Паттерн для цепочки: элемент.элемент.элемент...
    chain_pattern = f'(?:{combined_pattern})(?:\.(?:{combined_pattern}))+'

    matches = re.finditer(chain_pattern, text, re.UNICODE)

    for match in matches:
        full_match = match.group(0)
        logger.debug("[_extract_entity_chains] Processing full match: '%s'", full_match)

        # Разбиваем цепочку на элементы и извлекаем текст
        elements = []

        # Ищем все отдельные элементы в цепочке
        for i, element_pattern in enumerate(element_patterns):
            element_matches = re.finditer(element_pattern, full_match, re.UNICODE)
            for element_match in element_matches:
                # Для разных паттернов группы могут быть в разных местах
                element_text = None
                for group_idx in range(1, element_match.lastindex + 1 if element_match.lastindex else 1):
                    if element_match.group(group_idx):
                        element_text = element_match.group(group_idx).strip()
                        break

                if element_text and len(element_text.split()) <= 5:
                    # Дополнительная проверка для простых названий
                    if i == 4:  # Паттерн для простых названий (последний в списке)
                        # Проверяем, что это действительно похоже на название сущности
                        if len(element_text) >= 3 and not element_text.lower() in ['или', 'для', 'при', 'как', 'что',
                                                                                   'это']:
                            elements.append({
                                'text': element_text,
                                'position': element_match.start(),
                                'type': 'simple_name'
                            })
                    else:
                        elements.append({
                            'text': element_text,
                            'position': element_match.start(),
                            'type': 'formatted'
                        })

        # Сортируем элементы по позиции в исходном тексте
        elements.sort(key=lambda x: x['position'])

        if len(elements) >= 2:  # Минимум сущность.атрибут
            entities = [elem['text'] for elem in elements[:-1]]  # Все кроме последнего
            final_attribute = elements[-1]['text']  # Последний элемент

            chains.append({
                'entities': entities,
                'final_attribute': final_attribute,
                'full_match': full_match
            })

            logger.debug("[_extract_entity_chains] Found chain: entities=%s, attribute='%s'",
                         entities, final_attribute)

    return chains


# def _extract_text_from_formatting(formatted_text: str) -> str:
#     """
#     Извлекает текст из различных форматов оформления
#     """
#     text = formatted_text.strip()
#
#     # Двойные кавычки
#     if text.startswith('"') and text.endswith('"'):
#         return text[1:-1].strip()
#
#     # Одинарные кавычки
#     if text.startswith("'") and text.endswith("'"):
#         return text[1:-1].strip()
#
#     # Треугольные скобки
#     if text.startswith('<') and text.endswith('>'):
#         return text[1:-1].strip()
#
#     # Квадратные скобки (ссылки)
#     if text.startswith('[') and text.endswith(']'):
#         return text[1:-1].strip()
#
#     # Если ничего не подошло, возвращаем как есть (но это не должно происходить)
#     return text


# def _extract_hierarchical_entities(text: str) -> List[tuple]:
#     """
#     Извлекает иерархические ссылки типа [Сущность1].<[Сущность2]>.<атрибут>
#     """
#     hierarchical_entities = []
#
#     # Паттерн для иерархических ссылок: [Сущность].<[Сущность]>.<атрибут>
#     pattern = r'\[([^\]]+)\]\.<\[([^\]]+)\]>\.<([^>]+)>'
#
#     matches = re.finditer(pattern, text, re.UNICODE)
#
#     for match in matches:
#         parent_entity = match.group(1).strip()
#         child_entity = match.group(2).strip()
#         attribute_name = match.group(3).strip()
#
#         # ИСПРАВЛЕНИЕ: Очищаем названия сущностей
#         parent_clean = _clean_entity_name(parent_entity)
#         child_clean = _clean_entity_name(child_entity)
#
#         if parent_clean:
#             # Добавляем родительскую сущность со ссылкой на дочернюю как "атрибут"
#             hierarchical_entities.append((parent_clean, child_clean))
#
#         if child_clean:
#             # Добавляем дочернюю сущность с реальным атрибутом
#             hierarchical_entities.append((child_clean, attribute_name))
#
#         logger.debug(
#             "[_extract_hierarchical_entities] Found hierarchical: parent='%s'->%s, child='%s'->%s, attribute='%s'",
#             parent_entity, parent_clean, child_entity, child_clean, attribute_name)
#
#     return hierarchical_entities


# def _remove_hierarchical_patterns(text: str) -> str:
#     """
#     Удаляет иерархические паттерны из текста, чтобы они не мешали обычной обработке
#     """
#     # Заменяем иерархические ссылки на пустые строки
#     pattern = r'\[([^\]]+)\]\.<\[([^\]]+)\]>\.<([^>]+)>'
#     cleaned_text = re.sub(pattern, '', text, flags=re.UNICODE)
#
#     # Убираем лишние пробелы
#     cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
#
#     return cleaned_text


# def _clean_entity_name(entity_name: str) -> str:
#     """
#     Очищает название сущности от лишних слов в начале
#     """
#     # Список слов, которые нужно убрать из начала
#     stop_words_start = [
#         'проверить', 'проверяем', 'проверяется', 'проверим',
#         'установить', 'устанавливаем', 'устанавливается',
#         'значение', 'поле', 'атрибут', 'если', 'когда', 'при',
#         'в', 'на', 'для', 'по', 'со', 'из', 'от', 'до',
#         'должен', 'должна', 'должно', 'может', 'могут',
#         'является', 'равен', 'равна', 'равно'
#     ]
#
#     words = entity_name.split()
#
#     # Убираем стоп-слова с начала
#     while words and words[0].lower() in stop_words_start:
#         words.pop(0)
#
#     # Возвращаем очищенное название
#     cleaned = ' '.join(words).strip()
#
#     # Дополнительная проверка - должно остаться хотя бы 2 символа
#     if len(cleaned) < 2:
#         return ""
#
#     return cleaned


def extract_simple_keywords(text: str) -> List[str]:
    """
    Запасной метод: простое извлечение ключевых слов без LLM
    """
    logger.info("[extract_simple_keywords] Fallback keyword extraction")

    # Технические термины, которые часто встречаются в требованиях
    technical_terms = {
        'api', 'json', 'xml', 'rest', 'soap', 'http', 'https',
        'авторизация', 'аутентификация', 'токен', 'jwt',
        'база данных', 'бд', 'sql', 'таблица',
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


def _search_by_entity_title(entity_names: List[str], service_code: str, exclude_page_ids: Optional[List[str]],
                            embeddings_model) -> List:
    """
    Поиск страниц с точным совпадением title с именем сущности
    Это самый точный способ найти модель данных сущности
    """
    if not entity_names:
        return []

    logger.debug("[_search_by_entity_title] Searching by exact title match for entities: %s", entity_names)

    found_docs = []

    # 1. ПОИСК В ПЛАТФОРМЕННОМ dataModel
    platform_docs = _search_by_title_in_platform(entity_names, exclude_page_ids, embeddings_model)
    found_docs.extend(platform_docs)

    # 2. ПОИСК В СЕРВИСНОМ ХРАНИЛИЩЕ
    service_docs = _search_by_title_in_service(entity_names, service_code, exclude_page_ids, embeddings_model)
    found_docs.extend(service_docs)

    logger.info("[_search_by_entity_title] -> Found %d documents by exact title match", len(found_docs))
    return found_docs


def _search_by_title_in_platform(entity_names: List[str], exclude_page_ids: Optional[List[str]],
                                 embeddings_model) -> List:
    """Поиск по title в платформенном dataModel сервисе"""
    try:
        platform_store = get_vectorstore("platform_context", embedding_model=embeddings_model)

        # Получаем ВСЕ документы dataModel сервиса
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

        # Используем пустой запрос для получения всех документов с фильтром
        all_docs = platform_store.similarity_search("", k=1000, filter=filters)  # Большой k для получения всех

        # Фильтруем по точному совпадению title
        matched_docs = []
        for doc in all_docs:
            doc_title = doc.metadata.get('title', '').strip()
            for entity_name in entity_names:
                if doc_title == entity_name.strip():
                    matched_docs.append(doc)
                    logger.debug("[_search_by_title_in_platform] Exact match: '%s'", doc_title)
                    break

        return matched_docs

    except Exception as e:
        logger.error("[_search_by_title_in_platform] Error: %s", str(e))
        return []


def _search_by_title_in_service(entity_names: List[str], service_code: str, exclude_page_ids: Optional[List[str]],
                                embeddings_model) -> List:
    """Поиск по title в сервисном хранилище"""
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

        # Получаем все документы сервиса
        all_docs = service_store.similarity_search("", k=1000, filter=filters)

        # Фильтруем по точному совпадению title
        matched_docs = []
        for doc in all_docs:
            doc_title = doc.metadata.get('title', '').strip()
            for entity_name in entity_names:
                if doc_title == entity_name.strip():
                    matched_docs.append(doc)
                    logger.debug("[_search_by_title_in_service] Exact match in %s: '%s'", service_code, doc_title)
                    break

        return matched_docs

    except Exception as e:
        logger.error("[_search_by_title_in_service] Error: %s", str(e))
        return []


def extract_entity_names_from_requirements(requirements_text: str) -> List[str]:
    """
    Извлекает названия сущностей из текста требований для точного поиска по title
    """
    entity_names = []

    # Используем новый подход с цепочками
    entity_chains = _extract_entity_chains(requirements_text)

    for chain in entity_chains:
        for entity_name in chain['entities']:
            if entity_name not in entity_names and len(entity_name.split()) <= 5:
                entity_names.append(entity_name)

    logger.debug("[extract_entity_names_from_requirements] Found entity names: %s", entity_names)
    return entity_names