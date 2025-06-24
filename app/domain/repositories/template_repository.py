# app/domain/repositories/template_repository.py
from abc import ABC, abstractmethod
from typing import Optional, Dict, List


class TemplateRepository(ABC):
    """Абстракция для работы с шаблонами"""

    @abstractmethod
    async def get_template_by_type(self, requirement_type: str) -> Optional[str]:
        """Получение шаблона по типу требования"""
        pass

    @abstractmethod
    async def save_templates(self, templates: Dict[str, str]) -> int:
        """Сохранение шаблонов. Возвращает количество сохраненных"""
        pass

    @abstractmethod
    async def get_all_template_types(self) -> List[str]:
        """Получение всех доступных типов шаблонов"""
        pass

    @abstractmethod
    async def delete_template(self, requirement_type: str) -> bool:
        """Удаление шаблона"""
        pass