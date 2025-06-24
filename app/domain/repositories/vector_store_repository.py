# app/domain/repositories/vector_store_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from langchain_core.documents import Document


class VectorStoreRepository(ABC):
    """Абстракция для работы с векторным хранилищем"""

    @abstractmethod
    async def search_similar(
            self,
            query: str,
            filters: Optional[Dict[str, Any]] = None,
            k: int = 10
    ) -> List[Document]:
        """Поиск похожих документов"""
        pass

    @abstractmethod
    async def add_documents(self, documents: List[Document]) -> None:
        """Добавление документов в хранилище"""
        pass

    @abstractmethod
    async def delete_documents(self, filters: Dict[str, Any]) -> int:
        """Удаление документов по фильтрам. Возвращает количество удаленных"""
        pass

    @abstractmethod
    async def get_collection_stats(self) -> Dict[str, Any]:
        """Получение статистики коллекции"""
        pass

    @abstractmethod
    async def document_exists(self, filters: Dict[str, Any]) -> bool:
        """Проверка существования документа"""
        pass