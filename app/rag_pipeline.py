# app/rag_pipeline.py - дополненная версия
"""
Legacy обертка для app.rag_pipeline после рефакторинга.
Все функции теперь используют новые сервисы под капотом.
"""

import asyncio
import os
from typing import Optional, List, Dict, Any


# Legacy функции, которые теперь используют новые сервисы
def build_context(service_code: str, requirements_text: str = "", exclude_page_ids: Optional[List[str]] = None) -> str:
    """Legacy обертка для build_context"""
    from app.domain.services.context_builder import ContextBuilder

    builder = ContextBuilder()
    return asyncio.run(builder.build_context(service_code, requirements_text, exclude_page_ids))


def analyze_text(text: str, prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    """Legacy обертка для analyze_text"""
    from app.services.analysis_service import AnalysisService

    service = AnalysisService()
    return asyncio.run(service.analyze_text(text, prompt_template, service_code))


def analyze_pages(page_ids: List[str], prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    """Legacy обертка для analyze_pages"""
    from app.services.analysis_service import AnalysisService

    service = AnalysisService()
    return asyncio.run(service.analyze_pages(page_ids, prompt_template, service_code))


def analyze_with_templates(items: List[dict], prompt_template: Optional[str] = None,
                           service_code: Optional[str] = None):
    """Legacy обертка для analyze_with_templates"""
    from app.services.analysis_service import AnalysisService

    service = AnalysisService()
    return asyncio.run(service.analyze_with_templates(items, prompt_template, service_code))


def build_chain(prompt_template: Optional[str] = None):
    """Legacy обертка для build_chain"""
    from app.services.analysis_service import AnalysisService
    from langchain.chains.llm import LLMChain

    service = AnalysisService()
    return service._build_chain(prompt_template)


def count_tokens(text: str) -> int:
    """Legacy обертка для count_tokens"""
    from app.services.analysis_service import AnalysisService

    service = AnalysisService()
    return service._count_tokens(text)


def _prepare_search_queries(requirements_text: str) -> List[str]:
    """Legacy обертка для _prepare_search_queries"""
    from app.domain.services.context_builder import ContextBuilder

    builder = ContextBuilder()
    return builder._prepare_search_queries(requirements_text)


def _fast_deduplicate_documents(docs: List) -> List:
    """Legacy обертка для _fast_deduplicate_documents"""
    from app.domain.services.context_builder import ContextBuilder

    builder = ContextBuilder()
    return builder._fast_deduplicate_documents(docs)


def _smart_truncate_context(context: str, max_length: int) -> str:
    """Legacy обертка для _smart_truncate_context"""
    from app.domain.services.context_builder import ContextBuilder

    builder = ContextBuilder()
    return builder._smart_truncate_context(context, max_length)


def _extract_json_from_llm_response(response: str) -> Optional[str]:
    """Legacy обертка для _extract_json_from_llm_response"""
    from app.services.analysis_service import AnalysisService

    service = AnalysisService()
    return service._extract_json_from_llm_response(response)


def unified_service_search(queries: List[str], service_code: str, exclude_page_ids: Optional[List[str]],
                           k_per_query: int, embeddings_model) -> List:
    """Legacy обертка для unified_service_search"""
    from app.domain.services.context_builder import ContextBuilder

    builder = ContextBuilder()
    return asyncio.run(builder._unified_service_search(queries, service_code, exclude_page_ids, k_per_query))


def unified_platform_search(queries: List[str], exclude_page_ids: Optional[List[str]], k_per_query: int,
                            embeddings_model, exclude_services: Optional[List[str]] = None) -> List:
    """Legacy обертка для unified_platform_search"""
    from app.domain.services.context_builder import ContextBuilder

    builder = ContextBuilder()
    return asyncio.run(builder._unified_platform_search(queries, exclude_page_ids, k_per_query, exclude_services))


def build_template_analysis_chain(custom_prompt: Optional[str] = None):
    """Legacy обертка для build_template_analysis_chain"""
    from app.services.analysis_service import AnalysisService

    service = AnalysisService()
    return service._build_template_analysis_chain(custom_prompt)


# НЕДОСТАЮЩИЕ ФУНКЦИИ ИЗ ТЕСТОВ
def get_platform_services():
    """Legacy обертка для get_platform_services"""
    from app.service_registry import get_platform_services as orig_func
    return orig_func()


def extract_key_queries(requirements_text: str) -> List[str]:
    """Legacy обертка для extract_key_queries"""
    from app.semantic_search import extract_key_queries as orig_func
    return orig_func(requirements_text)


def resolve_service_code_by_user() -> str:
    """Legacy обертка для resolve_service_code_by_user"""
    from app.service_registry import resolve_service_code_by_user as orig_func
    return orig_func()


def resolve_service_code_from_pages_or_user(page_ids: List[str]) -> str:
    """Legacy обертка для resolve_service_code_from_pages_or_user"""
    from app.service_registry import resolve_service_code_from_pages_or_user as orig_func
    return orig_func(page_ids)


def get_page_content_by_id(page_id: str, clean_html: bool = True) -> Optional[str]:
    """Legacy обертка для get_page_content_by_id"""
    from app.confluence_loader import get_page_content_by_id as orig_func
    return orig_func(page_id, clean_html)


# Импорты для обратной совместимости
try:
    from langchain_core.prompts import PromptTemplate
    from langchain.chains.llm import LLMChain
    from app.llm_interface import get_llm, get_embeddings_model
    from app.config import LLM_PROVIDER, TEMPLATE_ANALYSIS_PROMPT_FILE, PAGE_ANALYSIS_PROMPT_FILE

    llm = get_llm()
except ImportError as e:
    # В тестовом режиме может не быть всех зависимостей
    pass