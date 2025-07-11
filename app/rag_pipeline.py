# app/rag_pipeline.py

import logging
from typing import Optional, List
import tiktoken
from bs4 import BeautifulSoup
from langchain_core.prompts import PromptTemplate
from langchain.chains.llm import LLMChain
from app.config import LLM_PROVIDER, TEMPLATE_ANALYSIS_PROMPT_FILE, PAGE_ANALYSIS_PROMPT_FILE
from app.confluence_loader import get_page_content_by_id, extract_approved_fragments
from app.llm_interface import get_llm
from app.style_utils import has_colored_style

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