# app/legacy/rag_pipeline_legacy.py
"""
Legacy обертки для обратной совместимости со старым кодом.
Используют новые сервисы под капотом.
"""
import logging
import asyncio
from typing import Optional, List
import os
if os.getenv('TESTING'):
    # В тестовом режиме используем тестовые адаптеры
    from tests.legacy_adapters import *
else:
    from app.services.analysis_service import AnalysisService
    from app.services.document_service import DocumentService

logger = logging.getLogger(__name__)

# Legacy функции для совместимости
def analyze_text(text: str, prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    """Legacy обертка для analyze_text"""
    service = AnalysisService()
    return asyncio.run(service.analyze_text(text, prompt_template, service_code))

def analyze_pages(page_ids: List[str], prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    """Legacy обертка для analyze_pages"""
    service = AnalysisService()
    return asyncio.run(service.analyze_pages(page_ids, prompt_template, service_code))

def analyze_with_templates(items: List[dict], prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    """Legacy обертка для analyze_with_templates"""
    service = AnalysisService()
    return asyncio.run(service.analyze_with_templates(items, prompt_template, service_code))

# Функции для работы с документами
def remove_service_fragments(page_ids: List[str]) -> int:
    """Legacy обертка для remove_service_fragments"""
    service = DocumentService()
    result = asyncio.run(service.remove_page_fragments(page_ids))
    return result.deleted_count