# app/semantic_search.py

import logging
import re
from typing import List, Set
from langchain_core.prompts import PromptTemplate
from langchain.chains.llm import LLMChain
from app.llm_interface import get_llm

logger = logging.getLogger(__name__)  # Лучше использовать __name__ для именованных логгеров

def extract_key_queries(requirements_text: str) -> List[str]:
    """
    Извлекает ключевые запросы из текста требований с помощью LLM
    для семантического поиска релевантных фрагментов.
    """
    logger.info("[extract_key_queries] <- text length: %d chars", len(requirements_text))

    if not requirements_text.strip():
        return []

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

Верни 5-8 наиболее важных ключевых запросов, каждый на новой строке:
"""

    try:
        llm = get_llm()
        prompt = PromptTemplate(
            input_variables=["requirements"],
            template=prompt_template
        )
        chain = LLMChain(llm=llm, prompt=prompt)

        result = chain.run(requirements=requirements_text)
        logger.debug("[extract_key_queries] Queries from LLM = {%s}", str(result))

        # Парсим результат
        queries = []
        for line in result.split('\n'):
            line = line.strip()
            # Убираем нумерацию и маркеры списков
            # line = re.sub(r'^\d+\.\s*', '', line)
            # line = re.sub(r'^[-*]\s*', '', line)

            # Обрабатываем начало строки
            # line = re.sub(r'^\d+\.\s*[-+*]+', '', line)  # Убираем цифры, точку, пробелы и спецсимволы
            line = re.sub(r'^\d+\.\s*[-+*]*', '', line)  # Убираем цифры, точку, пробелы и опциональные спецсимволы
            line = re.sub(r'^\[\[', '[', line)  # Заменяем двойные [[ на одинарные [
            # Обрабатываем конец строки
            line = re.sub(r'[\]+*-]+$', '', line)  # Убираем спецсимволы в конце
            if line and len(line) > 2:
                queries.append(line)

        # Ограничиваем количество запросов
        queries = queries[:8]

        logger.info("[extract_key_queries] -> extracted %d queries: %s", len(queries), queries)
        return queries

    except Exception as e:
        logging.error("[extract_key_queries] Error extracting queries: %s", str(e))
        # Fallback: простое извлечение ключевых слов
        return extract_simple_keywords(requirements_text)


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