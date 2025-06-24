# tests/test_di_container.py
"""
Тестовый DI контейнер с моками для unit тестов
"""
import pytest
from unittest.mock import Mock, AsyncMock
from typing import List, Optional, Dict, Any  # Добавил импорт
from langchain_core.documents import Document

from app.domain.repositories.vector_store_repository import VectorStoreRepository
from app.domain.repositories.confluence_repository import ConfluenceRepository
from app.domain.repositories.jira_repository import JiraRepository
from app.domain.repositories.template_repository import TemplateRepository
from app.domain.repositories.service_registry_repository import ServiceRegistryRepository

from app.services.document_service import DocumentService
from app.services.analysis_service import AnalysisService
from app.services.jira_service import JiraService


class MockVectorStoreRepository(VectorStoreRepository):
    """Мок векторного репозитория для тестов"""

    def __init__(self):
        self.documents = []
        self.deleted_count = 0

    async def search_similar(self, query: str, filters=None, k: int = 10):
        return [
            Document(
                page_content="Test context document",
                metadata={"page_id": "123", "service_code": "test", "title": "Test Page"}
            )
        ]

    async def add_documents(self, documents):
        self.documents.extend(documents)

    async def delete_documents(self, filters):
        self.deleted_count += 1
        return self.deleted_count

    async def get_collection_stats(self):
        return {
            "collection_name": "test_collection",
            "total_documents": len(self.documents),
            "doc_type_stats": {"requirement": len(self.documents)},
            "platform_stats": {"platform": 0, "regular": len(self.documents)},
            "service_stats": {"test": len(self.documents)},
            "sample_metadata": []
        }

    async def document_exists(self, filters):
        return len(self.documents) > 0


class MockConfluenceRepository(ConfluenceRepository):
    """Мок Confluence репозитория для тестов"""

    async def get_page_content(self, page_id: str, include_storage: bool = True):
        return {
            "id": page_id,
            "title": "Test Page",
            "raw_content": "<p>Test content</p>",
            "full_content": "Test content",
            "approved_content": "Test approved content"
        }

    async def get_page_title(self, page_id: str):
        return "Test Page"

    async def get_child_pages(self, page_id: str):
        return [
            {"id": "child1", "title": "Child Page 1", "parent_id": page_id},
            {"id": "child2", "title": "Child Page 2", "parent_id": page_id}
        ]

    async def load_pages_batch(self, page_ids):
        return [await self.get_page_content(pid) for pid in page_ids]

    async def check_page_exists(self, page_id: str):
        return True


class MockJiraRepository(JiraRepository):
    """Мок Jira репозитория для тестов"""

    async def get_task_description(self, task_id: str):
        return f'<div class="user-content-block"><a href="/pages/viewpage.action?pageId=123456789">Test Link</a></div>'

    async def extract_confluence_links(self, task_ids):
        return ["123456789"] * len(task_ids)

    async def check_task_exists(self, task_id: str):
        return True

    async def get_task_info(self, task_id: str):
        return {
            "task_id": task_id,
            "description": await self.get_task_description(task_id),
            "confluence_page_ids": ["123456789"],
            "confluence_pages_count": 1
        }


class MockTemplateRepository(TemplateRepository):
    """Мок репозитория шаблонов для тестов"""

    def __init__(self):
        self.templates = {
            "process": "<h1>Process Template</h1><p>Template content</p>"
        }

    async def get_template_by_type(self, requirement_type: str):
        return self.templates.get(requirement_type)

    async def save_templates(self, templates):
        self.templates.update(templates)
        return len(templates)

    async def get_all_template_types(self):
        return list(self.templates.keys())

    async def delete_template(self, requirement_type: str):
        if requirement_type in self.templates:
            del self.templates[requirement_type]
            return True
        return False


class MockServiceRegistryRepository(ServiceRegistryRepository):
    """Мок репозитория справочника сервисов для тестов"""

    def __init__(self):
        self.services = [
            {"code": "UAA", "name": "Authentication Service", "platform": True},
            {"code": "CC", "name": "Corporate Cards", "platform": False},
            {"code": "test", "name": "Test Service", "platform": False}
        ]

    async def get_all_services(self):
        return self.services

    async def get_service_by_code(self, code: str):
        for service in self.services:
            if service["code"] == code:
                return service
        return None

    async def get_platform_services(self):
        return [s for s in self.services if s.get("platform")]

    async def is_platform_service(self, service_code: str):
        service = await self.get_service_by_code(service_code)
        return service.get("platform", False) if service else False

    async def service_exists(self, service_code: str):
        return await self.get_service_by_code(service_code) is not None


class TestDIContainer:
    """Тестовый DI контейнер с моками"""

    def __init__(self):
        self._repositories = {}
        self._services = {}
        self._initialize_repositories()
        self._initialize_services()

    def _initialize_repositories(self):
        """Инициализация мок-репозиториев"""
        self._repositories[VectorStoreRepository] = MockVectorStoreRepository()
        self._repositories[ConfluenceRepository] = MockConfluenceRepository()
        self._repositories[JiraRepository] = MockJiraRepository()
        self._repositories[TemplateRepository] = MockTemplateRepository()
        self._repositories[ServiceRegistryRepository] = MockServiceRegistryRepository()

    def _initialize_services(self):
        """Инициализация сервисов с мок-репозиториями"""
        self._services[DocumentService] = DocumentService(
            vector_repo=self._repositories[VectorStoreRepository],
            confluence_repo=self._repositories[ConfluenceRepository],
            service_registry_repo=self._repositories[ServiceRegistryRepository],
            template_repo=self._repositories[TemplateRepository]
        )

        # Для AnalysisService и JiraService используем реальные классы
        # но с замоканными зависимостями
        self._services[AnalysisService] = AnalysisService()
        self._services[JiraService] = JiraService()

    def get_repository(self, repository_type: type):
        return self._repositories.get(repository_type)

    def get_service(self, service_type: type):
        return self._services.get(service_type)


# Глобальный тестовый контейнер
_test_container = None


def get_test_container() -> TestDIContainer:
    """Получение тестового контейнера"""
    global _test_container
    if _test_container is None:
        _test_container = TestDIContainer()
    return _test_container


# Тестовые dependencies
def get_test_document_service() -> DocumentService:
    return get_test_container().get_service(DocumentService)


def get_test_analysis_service() -> AnalysisService:
    return get_test_container().get_service(AnalysisService)


def get_test_jira_service() -> JiraService:
    return get_test_container().get_service(JiraService)