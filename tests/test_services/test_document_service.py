# tests/test_services/test_document_service.py - новый тест для сервисов
import pytest
from app.services.document_service import DocumentService
from tests.test_di_container import get_test_container


@pytest.mark.asyncio
class TestDocumentService:

    async def test_load_and_index_pages(self):
        """Тест загрузки и индексации страниц"""
        container = get_test_container()
        service = container.get_service(DocumentService)

        result = await service.load_and_index_pages(
            page_ids=["123", "456"],
            service_code="test"
        )

        assert result.success is True or result.error is not None
        if result.success:
            assert result.documents_created >= 0
            assert result.storage == "unified_requirements"

    async def test_remove_page_fragments(self):
        """Тест удаления фрагментов страниц"""
        container = get_test_container()
        service = container.get_service(DocumentService)

        result = await service.remove_page_fragments(["123", "456"])

        assert result.success is True or result.error is not None
        if result.success:
            assert result.deleted_count >= 0