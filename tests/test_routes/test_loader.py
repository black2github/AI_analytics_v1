# tests/test_routes/test_loader.py

import pytest
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient


class TestLoaderRoutes:

    @patch('app.routes.loader.load_pages_by_ids')
    @patch('app.routes.loader.get_vectorstore')
    @patch('app.routes.loader.get_embeddings_model')
    @patch('app.routes.loader.resolve_service_code_from_pages_or_user')
    def test_load_service_pages_success(self, mock_resolve, mock_embeddings,
                                        mock_vectorstore, mock_load_pages, app_client):
        """Тест успешной загрузки страниц сервиса"""
        # Настройка моков
        mock_resolve.return_value = "CC"
        mock_load_pages.return_value = [
            {
                "id": "123",
                "title": "Test Page",
                "content": "All content",
                "approved_content": "Approved content"
            }
        ]

        mock_store = Mock()
        mock_store.delete.return_value = None
        mock_store.add_documents.return_value = None
        mock_vectorstore.return_value = mock_store

        # Выполнение запроса
        response = app_client.post("/load_pages", json={
            "page_ids": ["123"],
            "service_code": "CC"
        })

        # Проверки
        assert response.status_code == 200
        data = response.json()
        assert "documents indexed" in data["message"]
        assert data["documents_created"] == 1

    @patch('app.routes.loader.load_pages_by_ids')
    def test_load_service_pages_no_approved_content(self, mock_load_pages, app_client):
        """Тест загрузки страниц без подтвержденного содержимого"""
        mock_load_pages.return_value = [
            {
                "id": "123",
                "title": "Test Page",
                "content": "All content",
                "approved_content": ""  # Нет подтвержденного содержимого
            }
        ]

        response = app_client.post("/load_pages", json={
            "page_ids": ["123"],
            "service_code": "CC"
        })

        assert response.status_code == 200
        data = response.json()
        assert "No pages with approved content found" in data["error"]

    @patch('app.routes.loader.get_child_page_ids')
    def test_get_child_pages_success(self, mock_get_children, app_client):
        """Тест получения дочерних страниц"""
        mock_get_children.return_value = ["child1", "child2"]

        response = app_client.get("/child_pages/parent123")

        assert response.status_code == 200
        data = response.json()
        assert data["page_ids"] == ["child1", "child2"]
        assert data["load_result"] is None

    @patch('app.routes.loader.remove_service_fragments')
    def test_remove_service_pages_success(self, mock_remove, app_client):
        """Тест удаления страниц сервиса"""
        mock_remove.return_value = 5

        response = app_client.post("/remove_service_pages", json={
            "page_ids": ["123", "456"]
        })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["deleted_count"] == 5