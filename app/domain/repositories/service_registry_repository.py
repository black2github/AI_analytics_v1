# app/domain/repositories/service_registry_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class ServiceRegistryRepository(ABC):
    """Абстракция для работы со справочником сервисов"""

    @abstractmethod
    async def get_all_services(self) -> List[Dict[str, Any]]:
        """Получение всех сервисов"""
        pass

    @abstractmethod
    async def get_service_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Получение сервиса по коду"""
        pass

    @abstractmethod
    async def get_platform_services(self) -> List[Dict[str, Any]]:
        """Получение платформенных сервисов"""
        pass

    @abstractmethod
    async def is_platform_service(self, service_code: str) -> bool:
        """Проверка, является ли сервис платформенным"""
        pass

    @abstractmethod
    async def service_exists(self, service_code: str) -> bool:
        """Проверка существования сервиса"""
        pass