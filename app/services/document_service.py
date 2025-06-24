# app/services/document_service.py - обновленная версия
import logging
from typing import List, Optional, Dict
from app.domain.models.document_models import (
    LoadResult, RemovalResult, ChildPagesResult, DebugInfo, DocumentType
)
from app.domain.repositories.vector_store_repository import VectorStoreRepository
from app.domain.repositories.confluence_repository import ConfluenceRepository
from app.domain.repositories.service_registry_repository import ServiceRegistryRepository
from app.domain.repositories.template_repository import TemplateRepository
from app.embedding_store import prepare_unified_documents
from app.config import UNIFIED_STORAGE_NAME

logger = logging.getLogger(__name__)


class DocumentServiceError(Exception):
    """Базовое исключение для DocumentService"""
    pass


class DocumentService:
    """Сервис для работы с документами и их индексацией"""

    def __init__(
            self,
            vector_repo: VectorStoreRepository,
            confluence_repo: ConfluenceRepository,
            service_registry_repo: ServiceRegistryRepository,
            template_repo: TemplateRepository
    ):
        self.vector_repo = vector_repo
        self.confluence_repo = confluence_repo
        self.service_registry_repo = service_registry_repo
        self.template_repo = template_repo
        self.storage_name = UNIFIED_STORAGE_NAME

    async def load_and_index_pages(
            self,
            page_ids: List[str],
            service_code: Optional[str] = None,
            source: str = "DBOCORPESPLN"
    ) -> LoadResult:
        """Загружает ТОЛЬКО подтвержденные требования в единое хранилище"""
        logger.info("[load_and_index_pages] <- page_ids=%s, service_code=%s, source=%s",
                    page_ids, service_code, source)

        try:
            # Определяем код сервиса
            resolved_service_code = service_code
            if not service_code:
                resolved_service_code = await self._resolve_service_code_from_pages_or_user(page_ids)
                if not resolved_service_code:
                    raise DocumentServiceError("Cannot resolve service_code. Please specify explicitly.")

            # Загружаем страницы с подтвержденным содержимым
            pages = await self.confluence_repo.load_pages_batch(page_ids)
            if not pages:
                raise DocumentServiceError("No pages found.")

            # Фильтруем страницы с подтвержденным содержимым
            pages_with_approved_content = self._filter_pages_with_approved_content(pages)

            if not pages_with_approved_content:
                return LoadResult(
                    success=False,
                    total_pages=len(page_ids),
                    pages_with_approved_content=0,
                    documents_created=0,
                    is_platform=False,
                    storage=self.storage_name,
                    message="No pages with approved content found.",
                    error="No pages with approved content found."
                )

            # Удаляем предыдущие фрагменты этих страниц
            await self._delete_existing_fragments(pages_with_approved_content)

            # Создаем документы с новой схемой метаданных
            docs = prepare_unified_documents(
                pages=pages_with_approved_content,
                service_code=resolved_service_code,
                doc_type=DocumentType.REQUIREMENT.value,
                source=source
            )

            if not docs:
                raise DocumentServiceError("No documents created from approved content.")

            # Индексируем документы
            await self.vector_repo.add_documents(docs)

            # Определяем платформенность для ответа
            is_platform = await self.service_registry_repo.is_platform_service(resolved_service_code)
            platform_status = "platform" if is_platform else "regular"

            logger.info("[load_and_index_pages] -> %d documents indexed for %s service '%s'",
                        len(docs), platform_status, resolved_service_code)

            return LoadResult(
                success=True,
                total_pages=len(page_ids),
                pages_with_approved_content=len(pages_with_approved_content),
                documents_created=len(docs),
                is_platform=is_platform,
                storage=self.storage_name,
                message=f"{len(docs)} documents indexed for {platform_status} service '{resolved_service_code}' (approved content only)."
            )

        except DocumentServiceError:
            raise
        except Exception as e:
            logger.error("[load_and_index_pages] Unexpected error: %s", str(e))
            raise DocumentServiceError(f"Failed to load and index pages: {str(e)}")

    async def load_templates(self, templates: Dict[str, str]) -> int:
        """Загружает шаблоны требований в единое хранилище"""
        logger.info("[load_templates] <- templates count: %d", len(templates))

        try:
            result = await self.template_repo.save_templates(templates)
            logger.info("[load_templates] -> Templates loaded: %d", result)
            return result
        except Exception as e:
            logger.error("[load_templates] Error: %s", str(e))
            raise DocumentServiceError(f"Failed to load templates: {str(e)}")

    async def get_child_pages(
            self,
            page_id: str,
            service_code: Optional[str] = None,
            source: str = "DBOCORPESPLN"
    ) -> ChildPagesResult:
        """Возвращает список дочерних страниц и загружает их при указании service_code"""
        logger.info("[get_child_pages] <- page_id=%s, service_code=%s, source=%s",
                    page_id, service_code, source)

        try:
            child_pages = await self.confluence_repo.get_child_pages(page_id)
            child_page_ids = [page["id"] for page in child_pages]

            if not child_page_ids:
                logger.info("[get_child_pages] No child pages found for page_id=%s", page_id)
                return ChildPagesResult(page_ids=[])

            result = ChildPagesResult(page_ids=child_page_ids)

            if service_code:
                logger.debug("[get_child_pages] Loading child pages for service: %s", service_code)
                load_result = await self.load_and_index_pages(
                    page_ids=child_page_ids,
                    service_code=service_code,
                    source=source
                )
                result.load_result = load_result

            logger.info("[get_child_pages] -> Found %d child pages", len(child_page_ids))
            return result

        except Exception as e:
            logger.error("[get_child_pages] Error: %s", str(e))
            raise DocumentServiceError(f"Failed to get child pages: {str(e)}")

    async def remove_page_fragments(self, page_ids: List[str]) -> RemovalResult:
        """Удаляет фрагменты указанных страниц из единого хранилища"""
        logger.info("[remove_page_fragments] <- page_ids=%s", page_ids)

        try:
            deleted_count = await self._remove_fragments_by_page_ids(page_ids)

            logger.info("[remove_page_fragments] -> Success, deleted %d fragments", deleted_count)
            return RemovalResult(
                success=True,
                deleted_count=deleted_count,
                page_ids=page_ids,
                storage=self.storage_name
            )
        except Exception as e:
            logger.error("[remove_page_fragments] Error: %s", str(e))
            return RemovalResult(
                success=False,
                deleted_count=0,
                page_ids=page_ids,
                storage=self.storage_name,
                error=str(e)
            )

    async def remove_platform_fragments(
            self,
            page_ids: List[str],
            service_code: str
    ) -> RemovalResult:
        """Удаляет фрагменты платформенных страниц из единого хранилища"""
        logger.info("[remove_platform_fragments] <- page_ids=%s, service_code=%s",
                    page_ids, service_code)

        try:
            is_platform = await self.service_registry_repo.is_platform_service(service_code)
            if not is_platform:
                raise DocumentServiceError(f"Service {service_code} is not a platform service")

            # Удаляем платформенные фрагменты
            deleted_count = await self.vector_repo.delete_documents({
                "$and": [
                    {"page_id": {"$in": page_ids}},
                    {"service_code": {"$eq": service_code}},
                    {"doc_type": {"$eq": DocumentType.REQUIREMENT.value}},
                    {"is_platform": {"$eq": True}}
                ]
            })

            logger.info("[remove_platform_fragments] -> Success, deleted %d platform fragments",
                        deleted_count)

            return RemovalResult(
                success=True,
                deleted_count=deleted_count,
                page_ids=page_ids,
                storage=self.storage_name
            )

        except DocumentServiceError:
            raise
        except Exception as e:
            logger.error("[remove_platform_fragments] Error: %s", str(e))
            raise DocumentServiceError(f"Failed to remove platform fragments: {str(e)}")

    async def get_debug_info(self) -> DebugInfo:
        """Возвращает отладочную информацию о едином хранилище"""
        try:
            stats = await self.vector_repo.get_collection_stats()

            return DebugInfo(
                storage_name=stats["collection_name"],
                total_documents=stats["total_documents"],
                doc_type_stats=stats["doc_type_stats"],
                platform_stats=stats["platform_stats"],
                service_stats=stats["service_stats"],
                sample_metadata=stats["sample_metadata"],
                status="ok"
            )

        except Exception as e:
            logger.error("[get_debug_info] Error: %s", str(e))
            raise DocumentServiceError(f"Failed to get debug info: {str(e)}")

    # Приватные методы
    def _filter_pages_with_approved_content(self, pages: List[Dict]) -> List[Dict]:
        """Фильтрует страницы с подтвержденным содержимым"""
        filtered_pages = []
        for page in pages:
            approved_content = page.get("approved_content", "")
            if approved_content and approved_content.strip():
                filtered_pages.append(page)
                logger.debug("[_filter_pages_with_approved_content] Page %s has approved content (%d chars)",
                             page["id"], len(approved_content))
            else:
                logger.warning("[_filter_pages_with_approved_content] Page %s has no approved content, skipping",
                               page["id"])
        return filtered_pages

    async def _delete_existing_fragments(self, pages: List[Dict]):
        """Удаляет существующие фрагменты страниц"""
        page_ids_to_delete = [p["id"] for p in pages]
        try:
            deleted_count = await self.vector_repo.delete_documents({
                "$and": [
                    {"page_id": {"$in": page_ids_to_delete}},
                    {"doc_type": {"$eq": DocumentType.REQUIREMENT.value}}
                ]
            })
            logger.debug("[_delete_existing_fragments] Deleted %d existing requirement fragments for page_ids: %s",
                         deleted_count, page_ids_to_delete)
        except Exception as e:
            logger.warning("[_delete_existing_fragments] Could not delete existing vectors: %s", e)

    async def _remove_fragments_by_page_ids(self, page_ids: List[str]) -> int:
        """Удаляет фрагменты по идентификаторам страниц"""
        if not page_ids:
            logger.warning("[_remove_fragments_by_page_ids] Empty page_ids list provided")
            return 0

        deleted_count = await self.vector_repo.delete_documents({
            "$and": [
                {"page_id": {"$in": page_ids}},
                {"doc_type": {"$eq": DocumentType.REQUIREMENT.value}}
            ]
        })

        logger.info("[_remove_fragments_by_page_ids] -> Deleted %d fragments for %d page_ids",
                    deleted_count, len(page_ids))
        return deleted_count

    async def _resolve_service_code_from_pages_or_user(self, page_ids: List[str]) -> Optional[str]:
        """Определяет код сервиса из страниц или пользователя"""
        # Пока используем простую логику - можно расширить
        # TODO: Реализовать поиск в векторном хранилище
        from app.service_registry import resolve_service_code_by_user
        return resolve_service_code_by_user()