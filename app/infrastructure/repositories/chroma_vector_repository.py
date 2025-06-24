# app/infrastructure/repositories/chroma_vector_repository.py
import logging
from typing import List, Optional, Dict, Any
from langchain_core.documents import Document

from app.domain.repositories.vector_store_repository import VectorStoreRepository
from app.embedding_store import get_vectorstore
from app.llm_interface import get_embeddings_model

logger = logging.getLogger(__name__)


class ChromaVectorRepository(VectorStoreRepository):
    """Реализация векторного репозитория для ChromaDB"""

    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.embeddings_model = get_embeddings_model()
        self._store = None

    @property
    def store(self):
        """Lazy инициализация store"""
        if self._store is None:
            self._store = get_vectorstore(self.collection_name, embedding_model=self.embeddings_model)
        return self._store

    async def search_similar(
            self,
            query: str,
            filters: Optional[Dict[str, Any]] = None,
            k: int = 10
    ) -> List[Document]:
        """Поиск похожих документов"""
        logger.debug("[search_similar] <- query='%s', filters=%s, k=%d",
                     query[:50], filters, k)

        try:
            if filters:
                docs = self.store.similarity_search(query, k=k, filter=filters)
            else:
                docs = self.store.similarity_search(query, k=k)

            logger.debug("[search_similar] -> Found %d documents", len(docs))
            return docs

        except Exception as e:
            logger.error("[search_similar] Error: %s", str(e))
            raise

    async def add_documents(self, documents: List[Document]) -> None:
        """Добавление документов в хранилище"""
        logger.info("[add_documents] <- Adding %d documents", len(documents))

        try:
            self.store.add_documents(documents)
            logger.info("[add_documents] -> Successfully added %d documents", len(documents))

        except Exception as e:
            logger.error("[add_documents] Error adding documents: %s", str(e))
            raise

    async def delete_documents(self, filters: Dict[str, Any]) -> int:
        """Удаление документов по фильтрам"""
        logger.info("[delete_documents] <- filters=%s", filters)

        try:
            # Подсчитываем количество документов до удаления
            initial_count = len(self.store.get()['ids'])

            # Удаляем документы
            self.store.delete(where=filters)

            # Подсчитываем количество документов после удаления
            final_count = len(self.store.get()['ids'])
            deleted_count = initial_count - final_count

            logger.info("[delete_documents] -> Deleted %d documents", deleted_count)
            return deleted_count

        except Exception as e:
            logger.error("[delete_documents] Error deleting documents: %s", str(e))
            raise

    async def get_collection_stats(self) -> Dict[str, Any]:
        """Получение статистики коллекции"""
        logger.debug("[get_collection_stats] <- Getting stats for collection '%s'", self.collection_name)

        try:
            data = self.store.get()

            # Статистика по типам документов
            doc_type_stats = {}
            platform_stats = {"platform": 0, "regular": 0}
            service_stats = {}

            if data.get('metadatas'):
                for metadata in data['metadatas']:
                    if metadata:
                        # Статистика по типам документов
                        doc_type = metadata.get('doc_type', 'unknown')
                        doc_type_stats[doc_type] = doc_type_stats.get(doc_type, 0) + 1

                        # Статистика по платформенности
                        is_platform = metadata.get('is_platform', False)
                        if is_platform:
                            platform_stats["platform"] += 1
                        else:
                            platform_stats["regular"] += 1

                        # Статистика по сервисам
                        service_code = metadata.get('service_code', 'unknown')
                        service_stats[service_code] = service_stats.get(service_code, 0) + 1

            stats = {
                "collection_name": self.collection_name,
                "total_documents": len(data.get('ids', [])),
                "doc_type_stats": doc_type_stats,
                "platform_stats": platform_stats,
                "service_stats": service_stats,
                "sample_metadata": data.get('metadatas', [])[:3] if data.get('metadatas') else []
            }

            logger.debug("[get_collection_stats] -> Stats: total=%d docs", stats["total_documents"])
            return stats

        except Exception as e:
            logger.error("[get_collection_stats] Error getting stats: %s", str(e))
            raise

    async def document_exists(self, filters: Dict[str, Any]) -> bool:
        """Проверка существования документа"""
        logger.debug("[document_exists] <- filters=%s", filters)

        try:
            docs = self.store.similarity_search("", k=1, filter=filters)
            exists = len(docs) > 0

            logger.debug("[document_exists] -> exists=%s", exists)
            return exists

        except Exception as e:
            logger.error("[document_exists] Error checking existence: %s", str(e))
            return False