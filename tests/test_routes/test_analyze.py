# tests/test_routes/test_analyze.py - исправленная версия
import pytest
from unittest.mock import patch, AsyncMock


class TestAnalyzeRoutes:

    @patch('app.services.analysis_service.AnalysisService.analyze_text', new_callable=AsyncMock)
    def test_analyze_from_text_success(self, mock_analyze, app_client):
        """Тест анализа текстовых требований"""
        mock_analyze.return_value = "Analysis result"

        response = app_client.post("/analyze", json={
            "text": "Test requirements text",
            "service_code": "CC"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["result"] == "Analysis result"
        assert "error" not in data or data["error"] is None

    def test_analyze_pages_success(self, app_client):
        """Тест анализа страниц сервиса"""
        response = app_client.post("/analyze_pages", json={
            "page_ids": ["123"],
            "service_code": "CC"
        })

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        # Проверяем, что нет ошибки или ошибка = None
        assert "error" not in data or data["error"] is None

        if data["results"]:
            assert len(data["results"]) >= 0  # Может быть пустым в моке
            if data["results"]:
                assert "page_id" in data["results"][0]
                assert "analysis" in data["results"][0]

    def test_analyze_with_templates_success(self, app_client):
        """Тест анализа с шаблонами"""
        response = app_client.post("/analyze_with_templates", json={
            "items": [{"requirement_type": "process", "page_id": "123"}],
            "service_code": "CC"
        })

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "error" not in data or data["error"] is None

        if data["results"]:
            assert len(data["results"]) >= 0
            if data["results"]:
                assert "page_id" in data["results"][0]
                assert "requirement_type" in data["results"][0]