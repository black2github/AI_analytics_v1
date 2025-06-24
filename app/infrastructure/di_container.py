# app/infrastructure/di_container.py
"""
Dependency Injection контейнер для управления зависимостями
"""
import logging
from app.domain.repositories.vector_store_repository import VectorStoreRepository
from app.domain.repositories.confluence_repository import ConfluenceRepository
from app.domain.repositories.jira_repository import JiraRepository
from app.domain.repositories.template_repository import TemplateRepository
from app.domain.repositories.service_registry_repository import ServiceRegistryRepository

from app.infrastructure.repositories.chroma_vector_repository import ChromaVectorRepository
from app.infrastructure.repositories.confluence_api_repository import ConfluenceApiRepository
from app.infrastructure.repositories.jira_api_repository import JiraApiRepository
from app.infrastructure.repositories.file_template_repository import FileTemplateRepository
from app.infrastructure.repositories.json_service_registry_repository import JsonServiceRegistryRepository

from app.services.document_service import DocumentService
from app.services.analysis_service import AnalysisService
from app.services.jira_service import JiraService
from app.config import UNIFIED_STORAGE_NAME

logger = logging.getLogger(__name__)


class DIContainer:
    """Контейнер для управления зависимостями"""

    def __init__(self):
        self._repositories = {}
        self._services = {}
        self._initialize_repositories()
        self._initialize_services()

    def _initialize_repositories(self):
        """Инициализация репозиториев"""
        logger.info("[DIContainer] Initializing repositories...")

        # Vector Store Repository
        self._repositories[VectorStoreRepository] = ChromaVectorRepository(UNIFIED_STORAGE_NAME)

        # External API Repositories
        self._repositories[ConfluenceRepository] = ConfluenceApiRepository()
        self._repositories[JiraRepository] = JiraApiRepository()

        # File-based Repositories
        self._repositories[TemplateRepository] = FileTemplateRepository()
        self._repositories[ServiceRegistryRepository] = JsonServiceRegistryRepository()

        logger.info("[DIContainer] Repositories initialized successfully")

    def _initialize_services(self):
        """Инициализация сервисов"""
        logger.info("[DIContainer] Initializing services...")

        # Document Service
        self._services[DocumentService] = DocumentService(
            vector_repo=self._repositories[VectorStoreRepository],
            confluence_repo=self._repositories[ConfluenceRepository],
            service_registry_repo=self._repositories[ServiceRegistryRepository],
            template_repo=self._repositories[TemplateRepository]
        )

        # Analysis Service (использует репозитории через ContextBuilder)
        self._services[AnalysisService] = AnalysisService()

        # Jira Service
        self._services[JiraService] = JiraService()

        logger.info("[DIContainer] Services initialized successfully")

    def get_repository(self, repository_type: type):
        """Получение репозитория по типу"""
        return self._repositories.get(repository_type)

    def get_service(self, service_type: type):
        """Получение сервиса по типу"""
        return self._services.get(service_type)


# Глобальный экземпляр контейнера
_container = None


def get_container() -> DIContainer:
    """Получение глобального контейнера"""
    global _container
    if _container is None:
        _container = DIContainer()
    return _container


# Dependencies для FastAPI
def get_document_service() -> DocumentService:
    """Dependency для получения DocumentService"""
    return get_container().get_service(DocumentService)


def get_analysis_service() -> AnalysisService:
    """Dependency для получения AnalysisService"""
    return get_container().get_service(AnalysisService)


def get_jira_service() -> JiraService:
    """Dependency для получения JiraService"""
    return get_container().get_service(JiraService)


def get_vector_repository() -> VectorStoreRepository:
    """Dependency для получения VectorStoreRepository"""
    return get_container().get_repository(VectorStoreRepository)


def get_confluence_repository() -> ConfluenceRepository:
    """Dependency для получения ConfluenceRepository"""
    return get_container().get_repository(ConfluenceRepository)


def get_jira_repository() -> JiraRepository:
    """Dependency для получения JiraRepository"""
    return get_container().get_repository(JiraRepository)