# app/domain/repositories/confluence_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class ConfluenceRepository(ABC):
    """Абстракция для работы с Confluence API"""

    @abstractmethod
    async def get_page_content(self, page_id: str, include_storage: bool = True) -> Optional[Dict[str, Any]]:
        """Получение содержимого страницы"""
        pass

    @abstractmethod
    async def get_page_title(self, page_id: str) -> Optional[str]:
        """Получение заголовка страницы"""
        pass

    @abstractmethod
    async def get_child_pages(self, page_id: str) -> List[Dict[str, Any]]:
        """Получение дочерних страниц"""
        pass

    @abstractmethod
    async def load_pages_batch(self, page_ids: List[str]) -> List[Dict[str, Any]]:
        """Батчевая загрузка страниц"""
        pass

    @abstractmethod
    async def check_page_exists(self, page_id: str) -> bool:
        """Проверка существования страницы"""
        pass