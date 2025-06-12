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
from app.semantic_search import extract_key_queries, deduplicate_documents
from app.filter_approved_fragments import has_colored_style

llm = get_llm()
logger = logging.getLogger(__name__)  # Лучше использовать __name__ для именованных логгеров

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
                template = file.read().strip()  # Удаляем лишние пробелы и переносы
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

    # Логируем шаблон промпта для отладки
    logger.info("[build_chain] -> prompt template: %s", prompt.template)
    logger.info("[build_chain] -> prompt input variables: %s", prompt.input_variables)

    return LLMChain(llm=llm, prompt=prompt)


# В app/rag_pipeline.py - ЗАМЕНИТЬ функцию build_context

def build_context(service_code: str, requirements_text: str = "", exclude_page_ids: Optional[List[str]] = None):
    """
    Формирует контекст для анализа с использованием семантического поиска.

    Args:
        service_code: Код сервиса
        requirements_text: Текст анализируемых требований для семантического поиска
        exclude_page_ids: Список ID страниц, исключаемых из контекста

    Returns:
        Строковый контекст, объединяющий содержимое документов
    """
    logger.info("[build_context] <- service_code=%s, requirements_length=%d, exclude_page_ids=%s",
                 service_code, len(requirements_text), exclude_page_ids)
    logger.debug("[build_context] <- requirements = {%s}")

    embeddings_model = get_embeddings_model()

    # СОЗДАЕМ ФИЛЬТРЫ В НАЧАЛЕ - ОДИН РАЗ
    filters = {"service_code": {"$eq": service_code}}
    if exclude_page_ids:
        filters = {
            "$and": [
                {"service_code": {"$eq": service_code}},
                {"page_id": {"$nin": exclude_page_ids}}
            ]
        }

    logger.debug("[build_context] Using service filters: %s", filters)

    # 0 ИЗВЛЕКАЕМ КЛЮЧЕВЫЕ ЗАПРОСЫ ИЗ АНАЛИЗИРУЕМЫХ ТРЕБОВАНИЙ
    dumb_query = "" # Если нет требований - используем простую фильтрацию
    key_queries = None # Семантический поиск по каждому ключевому запросу
    fallback_query = None # Fallback: поиск по первым словам требований

    if requirements_text.strip():
        # Извлекаем ключевые запросы из анализируемых требований
        key_queries = extract_key_queries(requirements_text)
        if key_queries:
            logger.debug("[build_context] %d queries extracted", len(key_queries))
        else:
            logging.warning("[build_context] No key queries extracted, using fallback search")
            # Fallback: поиск по первым словам требований
            fallback_query = " ".join(requirements_text.split()[:10])
    else:
        logger.warning("[build_context] No requirements text provided, using basic filter search")
        # Если нет текста требований - используем простую фильтрацию
        dumb_query = ""

    # 1. СЕМАНТИЧЕСКИЙ ПОИСК ПО СЕРВИСНЫМ ТРЕБОВАНИЯМ
    service_docs = []
    service_store = get_vectorstore("service_pages", embedding_model=embeddings_model)

    if key_queries:
        logger.debug("[build_context] Using semantic search with %d queries", len(key_queries))

        # Семантический поиск по каждому ключевому запросу
        for query in key_queries:
            try:
                docs = service_store.similarity_search(
                    query,
                    k=3,  # Топ-3 наиболее релевантных документа
                    filter=filters
                )
                service_docs.extend(docs)
                logger.debug("[build_context] Query '%s' found %d docs", query, len(docs))
            except Exception as e:
                logging.warning("[build_context] Error searching for query '%s': %s", query, str(e))

        # Удаляем дубликаты
        service_docs = deduplicate_documents(service_docs)
    elif fallback_query:
        logging.warning("[build_context] No key queries extracted, using fallback search")
        # Fallback: поиск по первым словам требований
        service_docs = service_store.similarity_search(fallback_query, k=5, filter=filters)
    else:
        logger.warning("[build_context] No requirements text provided, using basic filter search")
        # Если нет текста требований - используем простую фильтрацию
        service_docs = service_store.similarity_search(dumb_query, k=10, filter=filters)

    logger.debug("[build_context] Service context = {%s}", str(service_docs))

    # 2. СЕМАНТИЧЕСКИЙ ПОИСК ПО ПЛАТФОРМЕННЫМ ТРЕБОВАНИЯ
    platform_docs = []
    platform_services = get_platform_services()
    platform_store = get_vectorstore("platform_context", embedding_model=embeddings_model)
    plat_docs = None

    # поиск по всем платформенным сервисам
    for plat in platform_services:
        # filters = {"service_code": plat["code"]}
        filters = {"service_code": {"$eq": plat["code"]}}
        if exclude_page_ids:
            filters = {
                "$and": [
                    {"service_code": {"$eq": plat["code"]}},
                    {"page_id": {"$nin": exclude_page_ids}}
                ]
            }
        logger.debug("[build_context] Using platform filters: %s", filters)
        if key_queries:
            # Семантический поиск по каждому ключевому запросу
            for query in key_queries:
                try:
                    plat_docs = platform_store.similarity_search(query, k=3, filter=filters)
                    platform_docs.extend(plat_docs)
                except Exception as e:
                    logging.warning("[build_context] Error loading platform service %s: %s", plat["code"], str(e))

                logger.debug("[build_context] Query '%s' found %d docs in platform service '%s'",
                             query, len(plat_docs), plat["code"])

        elif fallback_query:
            # Fallback: поиск по первым словам требований по всем платформенным сервисам
            try:
                plat_docs = platform_store.similarity_search(fallback_query, k=5, filter=filters)
                platform_docs.extend(plat_docs)
            except Exception as e:
                logging.warning("[build_context] Error loading platform service %s: %s", plat["code"], str(e))
            logger.debug("[build_context] Query '%s' found %d docs in platform service '%s'",
                         fallback_query, len(plat_docs), plat["code"])

        else:
            # Если нет текста требований - используем простую фильтрацию по всем платформенным сервисам
            try:
                plat_docs = platform_store.similarity_search(dumb_query, k=5, filter=filters)
                platform_docs.extend(plat_docs)
            except Exception as e:
                logging.warning("[build_context] Error loading platform service %s: %s", plat["code"], str(e))
            logger.debug("[build_context] Query '%s' found %d docs in platform service '%s'",
                         dumb_query, len(plat_docs), plat["code"])

    platform_docs = deduplicate_documents(platform_docs)
    logger.debug("[build_context] Platform context = {%s}", str(platform_docs))

    # for plat in platform_services:
    #     # поиск по всем платформенным сервисам
    #     try:
    #         plat_docs = platform_store.similarity_search("", k=5, filter={"service_code": plat["code"]})
    #         platform_docs.extend(plat_docs)
    #     except Exception as e:
    #         logging.warning("[build_context] Error loading platform service %s: %s", plat["code"], str(e))
    # logger.debug("[build_context] Platform context = {%s}", str(platform_docs))

    # 3. ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ ИЗ ССЫЛОК НЕПОДТВЕРЖДЕННЫХ ТРЕБОВАНИЙ
    linked_docs = []
    if exclude_page_ids:
        linked_page_ids = set()

        for page_id in exclude_page_ids:
            try:
                content = get_page_content_by_id(page_id, clean_html=False)
                if not content:
                    logger.debug("[build_context] No content for page_id=%s", page_id)
                    continue

                soup = BeautifulSoup(content, 'html.parser')

                # Счетчики для отладки
                colored_elements_count = 0
                links_found_count = 0

                # Ищем все элементы, которые могут содержать цветной текст
                for element in soup.find_all(["p", "li", "span", "div", "td", "th"]):
                    # ИСПОЛЬЗУЕМ СУЩЕСТВУЮЩУЮ ФУНКЦИЮ
                    if not has_colored_style(element):
                        continue

                    colored_elements_count += 1

                    # Расширенный поиск ссылок Confluence
                    found_links = _extract_confluence_links_from_element(element)

                    for linked_page_id in found_links:
                        if linked_page_id not in exclude_page_ids and linked_page_id not in linked_page_ids:
                            linked_page_ids.add(linked_page_id)
                            links_found_count += 1
                            logger.debug("[build_context] Found link to page_id=%s from colored element in page_id=%s",
                                          linked_page_id, page_id)

                logger.debug("[build_context] Page %s: colored_elements=%d, unique_links_found=%d",
                              page_id, colored_elements_count, links_found_count)

            except Exception as e:
                logger.error("[build_context] Error processing page_id=%s: %s", page_id, str(e))

        # Ограничиваем количество связанных страниц
        max_linked_pages = 3
        linked_page_ids_list = list(linked_page_ids)[:max_linked_pages]

        logger.info("[build_context] Found %d total linked pages, processing %d",
                     len(linked_page_ids), len(linked_page_ids_list))

        # Загружаем ПОДТВЕРЖДЕННОЕ содержимое связанных страниц
        for linked_page_id in linked_page_ids_list:
            try:
                linked_html = get_page_content_by_id(linked_page_id, clean_html=False)
                if linked_html:
                    # ИСПОЛЬЗУЕМ filter_approved_fragments для извлечения ТОЛЬКО подтвержденных требований
                    approved_content = extract_approved_fragments(linked_html)
                    if approved_content and approved_content.strip():
                        linked_docs.append(approved_content)
                        logger.debug("[build_context] Added approved content from linked page_id=%s (%d chars)",
                                      linked_page_id, len(approved_content))
                    else:
                        logger.debug("[build_context] No approved content in linked page_id=%s", linked_page_id)
                else:
                    logger.debug("[build_context] No content for linked page_id=%s", linked_page_id)
            except Exception as e:
                logger.error("[build_context] Error loading linked page_id=%s: %s", linked_page_id, str(e))

        logger.info("[build_context] Added %d linked documents to context", len(linked_docs))

    logger.debug("[build_context] Linked page context = {%s}", str(linked_docs))

    # 4. ОБЪЕДИНЯЕМ КОНТЕКСТ
    context_parts = [d.page_content for d in service_docs + platform_docs] + linked_docs
    context = "\n\n".join(context_parts) if context_parts else ""

    # 5. ОГРАНИЧИВАЕМ ДЛИНУ КОНТЕКСТА
    max_context_length = 16000
    if len(context) > max_context_length:
        context = context[:max_context_length]
        logger.info("[build_context] Context truncated to %d characters", max_context_length)

    logger.info("[build_context] -> Context: service_docs=%d, platform_docs=%d, linked_docs=%d, total_length=%d",
                 len(service_docs), len(platform_docs), len(linked_docs), len(context))
    logger.debug("[build_context] context = {%s}", context)
    return context


def _extract_confluence_links_from_element(element) -> List[str]:
    """
    Извлекает все ссылки на страницы Confluence из элемента.
    Поддерживает разные форматы ссылок Confluence.
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
                # (требует дополнительного API вызова к Confluence)
                content_title = ri_page.get('ri:content-title')
                if content_title:
                    # Здесь можно добавить резолвинг названия в page_id
                    logger.debug("[_extract_confluence_links] Found link by title: %s (not resolved)", content_title)

    # 3. Прямые ri:page теги (иногда встречаются отдельно)
    for ri_page in element.find_all('ri:page'):
        page_id = ri_page.get('ri:content-id')
        if page_id:
            page_ids.append(page_id)

    return list(set(page_ids))  # Убираем дубликаты


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


_encoding = tiktoken.get_encoding("cl100k_base") # Заменить на токенизатор DeepSeek, если доступен
def count_tokens(text: str) -> int:
    """Подсчитывает количество токенов в тексте с помощью токенизатора tiktoken."""
    if LLM_PROVIDER == "deepseek":
        # from transformers import AutoTokenizer
        # tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL)
        # return len(tokenizer.encode(text))
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


def analyze_with_templates(items: List[dict], prompt_template: Optional[str] = None, service_code: Optional[str] = None):
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
            formatting_issues.append(f"Несоответствие заголовков: ожидаются {template_headers}, найдены {content_headers}")

        template_tables = template_soup.find_all('table')
        content_tables = content_soup.find_all('table')
        if len(template_tables) != len(content_tables):
            formatting_issues.append(f"Несоответствие количества таблиц: ожидается {len(template_tables)}, найдено {len(content_tables)}")

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