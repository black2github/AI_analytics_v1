# app/rag_pipeline.py

import logging
import json
import re
from typing import Optional, List, Dict, Any
import markdownify
from markdownify import markdownify
import tiktoken
from bs4 import BeautifulSoup
from langchain_core.prompts import PromptTemplate
from langchain.chains.llm import LLMChain
from app.config import LLM_PROVIDER, LLM_MODEL
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
                    # Пропускаем элементы без цвета (по умолчанию, обычно черный в Confluence)
                    # или с черным цветом
                    if "color" not in style:
                        logging.debug("[build_context] Skipping element for page_id=%s: no color style (default)",
                                      page_id)
                        continue
                    if "rgb(0,0,0)" in style or "#000000" in style:
                        logging.debug("[build_context] Skipping element for page_id=%s: black color", page_id)
                        continue

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

    # Ограничиваем длину контекста - для безопасности ставь нижнюю границу (4000 символов, а не токенов),
    # чтобы гарантировать, что контекст не превысит возможные ограничения модели
    max_context_length = 16000
    if len(context) > max_context_length:
        context = context[:max_context_length]
        logging.info("[build_context] Context truncated to %d characters", max_context_length)

    logging.info("[build_context] -> Context length: %d characters, linked_pages: %d",
                 len(context), len(linked_docs))
    return context

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
            logging.error("[count_tokens] Error counting tokens: %s", str(e))
            return len(text.split())  # Запасной вариант: подсчет слов


def analyze_text(text: str, prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    logging.info("[analyze_text] <- text={%s}, prompt_template=..., service_code={%s}", text, service_code)
    if not service_code:
        service_code = resolve_service_code_by_user()
        logging.info("[analyze_text] Resolved service_code: %s", service_code)

    chain = build_chain(prompt_template)
    context = build_context(service_code)
    try:
        result = chain.run({"requirement": text, "context": context})
        logging.info("[analyze_text] -> result={%s}", result)
        return result
    except Exception as e:
        if "token limit" in str(e).lower():
            logging.error("[analyze_text] Token limit exceeded: %s", str(e))
            return {"error": "Превышен лимит токенов модели. Уменьшите объем текста или контекста."}
        raise


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
    logging.info("[analyze_pages] <- page_ids={%s}, service_code={%s}", page_ids, service_code)
    try:
        if not service_code:
            service_code = resolve_service_code_from_pages_or_user(page_ids)
            logging.debug("[analyze_pages] Resolved service_code: %s", service_code)

        requirements = []
        valid_page_ids = []
        max_tokens = 32000
        max_context_tokens = max_tokens // 2  # Ограничиваем контекст половиной лимита
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
        context = build_context(service_code, exclude_page_ids=page_ids)
        context_tokens = count_tokens(context)
        if context_tokens > max_context_tokens:
            logging.warning("[analyze_pages] Context too large (%d tokens), limiting analysis to %d pages",
                            context_tokens, len(valid_page_ids))
            return [{"page_id": pid, "analysis": "Анализ невозможен: контекст слишком большой"} for pid in valid_page_ids]

        full_prompt = PromptTemplate(
            input_variables=["requirement", "context"],
            template=template
        ).format(requirement=requirements_text, context=context)
        total_tokens = count_tokens(full_prompt)

        logging.debug("[analyze_pages] Tokens: requirements=%d, context=%d, template=%d, total=%d",
                      current_tokens, context_tokens, template_tokens, total_tokens)

        if total_tokens > max_tokens:
            logging.warning("[analyze_pages] Total tokens (%d) exceed max_tokens (%d)", total_tokens, max_tokens)
            return [{"page_id": pid, "analysis": "Анализ невозможен: превышен лимит токенов"} for pid in valid_page_ids]

        logging.info("[analyze_pages] requirements_text = {%s}", requirements_text)
        logging.info("[analyze_pages] full_prompt = {%s}", str(full_prompt))

        chain = build_chain(prompt_template)
        try:
            result = chain.run({"requirement": requirements_text, "context": context})
            cleaned_result = result.strip().strip("```json\n").strip("```")
            parsed_result = json.loads(cleaned_result)
            if not isinstance(parsed_result, dict):
                logging.error("[analyze_pages] Result is not a dictionary: %s", result)
                raise ValueError("Ожидался JSON-объект с ключами page_id")

            results = []
            for page_id in valid_page_ids:
                analysis = parsed_result.get(page_id, "Анализ не найден для этой страницы")
                results.append({"page_id": page_id, "analysis": analysis})
            logging.info("[analyze_pages] -> Result:\n[%s]", results)
            return results
        except Exception as e:
            if "token limit" in str(e).lower():
                logging.error("[analyze_pages] Token limit exceeded: %s", str(e))
                return [{"page_id": pid, "analysis": "Ошибка: превышен лимит токенов модели"} for pid in valid_page_ids]
            logging.error("[analyze_pages] Error in LLM chain: %s", str(e))
            raise
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