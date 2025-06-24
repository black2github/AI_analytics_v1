# tests/conftest.py - обновленная версия
import pytest
import tempfile
import shutil
import os
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from langchain_core.documents import Document

# Устанавливаем тестовую переменную окружения
os.environ['TESTING'] = 'true'

# Импорт тестового DI контейнера
from tests.test_di_container import (
    get_test_container, get_test_document_service,
    get_test_analysis_service, get_test_jira_service
)


# Мокаем внешние зависимости до импорта приложения
@pytest.fixture(autouse=True)
def mock_external_dependencies():
    """Автоматически мокает все внешние зависимости для каждого теста"""
    with patch('app.config.OPENAI_API_KEY', 'test-key'), \
            patch('app.config.CONFLUENCE_BASE_URL', 'http://test-confluence.com'), \
            patch('app.config.CONFLUENCE_USER', 'test-user'), \
            patch('app.config.CONFLUENCE_PASSWORD', 'test-password'), \
            patch('app.config.CHROMA_PERSIST_DIR', '/tmp/test-chroma'), \
            patch('app.llm_interface.get_llm') as mock_get_llm, \
            patch('app.llm_interface.get_embeddings_model') as mock_get_embeddings:
        # Настройка моков для LLM и embeddings
        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(content='{"test_page_id": "Test analysis result"}')
        mock_get_llm.return_value = mock_llm

        mock_embeddings = Mock()
        mock_embeddings.embed_query.return_value = [0.1] * 384
        mock_embeddings.embed_documents.return_value = [[0.1] * 384] * 3
        mock_get_embeddings.return_value = mock_embeddings

        yield


@pytest.fixture
def app_client():
    """FastAPI тест клиент с мокированными зависимостями"""
    # Патчим DI контейнер для использования тестовых зависимостей
    with patch('app.infrastructure.di_container.get_document_service', get_test_document_service), \
            patch('app.infrastructure.di_container.get_analysis_service', get_test_analysis_service), \
            patch('app.infrastructure.di_container.get_jira_service', get_test_jira_service), \
            patch('app.api.routes.loader.get_document_service', get_test_document_service), \
            patch('app.api.routes.analyze.get_analysis_service', get_test_analysis_service), \
            patch('app.api.routes.jira.get_jira_service', get_test_jira_service):
        from app.main import app
        return TestClient(app)


@pytest.fixture
def temp_dir():
    """Временная директория для тестов"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_services():
    """Тестовые данные сервисов"""
    return [
        {"code": "UAA", "name": "Authentication Service", "platform": True},
        {"code": "CC", "name": "Corporate Cards", "platform": False},
        {"code": "SBP", "name": "Fast Payment System", "platform": False}
    ]


@pytest.fixture
def sample_pages():
    """Тестовые данные страниц"""
    return [
        {
            "id": "12345",
            "title": "Test Requirements Page",
            "raw_content": "<p>All content</p><p style='color: red;'>New requirement</p>",
            "full_content": "All content New requirement",
            "approved_content": "All content"
        },
        {
            "id": "67890",
            "title": "Another Page",
            "raw_content": "<p>More content</p>",
            "full_content": "More content",
            "approved_content": "More content"
        }
    ]


# Новые фикстуры для тестирования сервисов
@pytest.fixture
def document_service():
    """Тестовый DocumentService"""
    return get_test_document_service()


@pytest.fixture
def analysis_service():
    """Тестовый AnalysisService"""
    return get_test_analysis_service()


@pytest.fixture
def jira_service():
    """Тестовый JiraService"""
    return get_test_jira_service()


@pytest.fixture
def test_container():
    """Тестовый DI контейнер"""
    return get_test_container()


# Legacy compatibility
@pytest.fixture
def mock_llm():
    """Мок LLM модели (для обратной совместимости)"""
    llm = Mock()
    llm.invoke.return_value = Mock(content='{"test_page_id": "Test analysis result"}')
    return llm


@pytest.fixture
def mock_embeddings():
    """Мок embedding модели (для обратной совместимости)"""
    embeddings = Mock()
    embeddings.embed_query.return_value = [0.1] * 384
    embeddings.embed_documents.return_value = [[0.1] * 384] * 3
    return embeddings


@pytest.fixture
def mock_vectorstore():
    """Мок векторного хранилища (для обратной совместимости)"""
    store = Mock()
    store.similarity_search.return_value = [
        Document(
            page_content="Test context document",
            metadata={"page_id": "123", "service_code": "test", "title": "Test Page"}
        )
    ]
    store.add_documents.return_value = None
    store.delete.return_value = None
    store.get.return_value = {'ids': ['id1', 'id2', 'id3']}
    return store


@pytest.fixture
def mock_confluence():
    """Мок Confluence API (для обратной совместимости)"""
    confluence = Mock()
    confluence.get_page_by_id.return_value = {
        'body': {
            'storage': {
                'value': '<p>Test page content</p>'
            }
        },
        'title': 'Test Page'
    }
    confluence.get_child_pages.return_value = [
        {'id': 'child1', 'title': 'Child Page 1'},
        {'id': 'child2', 'title': 'Child Page 2'}
    ]
    return confluence


# Дополнительные патчи для тестов RAG pipeline
@pytest.fixture(autouse=True)
def mock_llm_calls():
    """Патчит реальные вызовы LLM в тестах"""
    with patch('app.services.analysis_service.AnalysisService.analyze_text',
               new_callable=AsyncMock) as mock_analyze_text, \
            patch('app.services.analysis_service.AnalysisService.analyze_pages',
                  new_callable=AsyncMock) as mock_analyze_pages, \
            patch('app.llm_interface.get_llm') as mock_get_llm:
        # Настройка моков
        mock_analyze_text.return_value = "Test analysis result"
        mock_analyze_pages.return_value = [{"page_id": "123", "analysis": "Test analysis"}]

        mock_llm = Mock()
        mock_llm.invoke.return_value = Mock(content='{"test_page_id": "Test analysis result"}')
        mock_get_llm.return_value = mock_llm

        yield {
            "analyze_text": mock_analyze_text,
            "analyze_pages": mock_analyze_pages,
            "llm": mock_llm
        }