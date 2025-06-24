# tests/legacy_adapters.py
"""
Legacy адаптеры для обратной совместимости тестов
"""
import asyncio
import os
from typing import List, Optional, Dict, Any

# Проверяем, что мы в тестовом режиме
if not os.getenv('TESTING'):
    raise ImportError("Legacy adapters should only be used in test mode")

# Импортируем nest_asyncio сразу (должен быть установлен через requirements-test.txt)
try:
    import nest_asyncio

    nest_asyncio.apply()
except ImportError:
    pass  # Если нет nest_asyncio, работаем без него

from tests.test_di_container import get_test_container
from app.services.analysis_service import AnalysisService
from app.services.document_service import DocumentService
from app.domain.repositories.confluence_repository import ConfluenceRepository


def _run_async(coro):
    """Запуск async функции в sync контексте"""
    try:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)
    except RuntimeError:
        # Создаем новый цикл событий
        return asyncio.run(coro)


# Legacy функции для совместимости с существующими тестами
def analyze_text(text: str, prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    """Legacy адаптер для analyze_text"""
    service = get_test_container().get_service(AnalysisService)
    return _run_async(service.analyze_text(text, prompt_template, service_code))


def analyze_pages(page_ids: List[str], prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    """Legacy адаптер для analyze_pages"""
    service = get_test_container().get_service(AnalysisService)
    return _run_async(service.analyze_pages(page_ids, prompt_template, service_code))


def analyze_with_templates(items: List[dict], prompt_template: Optional[str] = None,
                           service_code: Optional[str] = None):
    """Legacy адаптер для analyze_with_templates"""
    service = get_test_container().get_service(AnalysisService)
    return _run_async(service.analyze_with_templates(items, prompt_template, service_code))


def remove_service_fragments(page_ids: List[str]) -> int:
    """Legacy адаптер для remove_service_fragments"""
    service = get_test_container().get_service(DocumentService)
    result = _run_async(service.remove_page_fragments(page_ids))
    return result.deleted_count


def load_pages_by_ids(page_ids: List[str]) -> List[Dict[str, str]]:
    """Legacy адаптер для load_pages_by_ids"""
    repo = get_test_container().get_repository(ConfluenceRepository)
    pages = _run_async(repo.load_pages_batch(page_ids))

    # Преобразуем в старый формат
    legacy_pages = []
    for page in pages:
        legacy_pages.append({
            "id": page["id"],
            "title": page["title"],
            "content": page.get("full_content", ""),
            "approved_content": page.get("approved_content", "")
        })

    return legacy_pages


def get_child_page_ids(page_id: str) -> List[str]:
    """Legacy адаптер для get_child_page_ids"""
    repo = get_test_container().get_repository(ConfluenceRepository)
    child_pages = _run_async(repo.get_child_pages(page_id))
    return [page["id"] for page in child_pages]


def get_page_content_by_id(page_id: str, clean_html: bool = True) -> Optional[str]:
    """Legacy адаптер для get_page_content_by_id"""
    repo = get_test_container().get_repository(ConfluenceRepository)
    page_data = _run_async(repo.get_page_content(page_id, include_storage=True))

    if not page_data:
        return None

    if clean_html:
        return page_data.get("full_content")
    else:
        return page_data.get("raw_content")


def get_page_title_by_id(page_id: str) -> Optional[str]:
    """Legacy адаптер для get_page_title_by_id"""
    repo = get_test_container().get_repository(ConfluenceRepository)
    return _run_async(repo.get_page_title(page_id))