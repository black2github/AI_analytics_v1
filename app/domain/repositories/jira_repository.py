# app/domain/repositories/jira_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class JiraRepository(ABC):
    """Абстракция для работы с Jira API"""

    @abstractmethod
    async def get_task_description(self, task_id: str) -> Optional[str]:
        """Получение описания задачи"""
        pass

    @abstractmethod
    async def extract_confluence_links(self, task_ids: List[str]) -> List[str]:
        """Извлечение ссылок на Confluence из задач"""
        pass

    @abstractmethod
    async def check_task_exists(self, task_id: str) -> bool:
        """Проверка существования задачи"""
        pass

    @abstractmethod
    async def get_task_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Получение информации о задаче"""
        pass