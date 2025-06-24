# app/infrastructure/repositories/json_service_registry_repository.py
import logging
from typing import List, Dict, Optional, Any

from app.domain.repositories.service_registry_repository import ServiceRegistryRepository
from app.service_registry import load_services, get_service_by_code, get_platform_services, is_platform_service

logger = logging.getLogger(__name__)


class JsonServiceRegistryRepository(ServiceRegistryRepository):
    """Реализация репозитория справочника сервисов через JSON файл"""

    async def get_all_services(self) -> List[Dict[str, Any]]:
        """Получение всех сервисов"""
        logger.debug("[get_all_services] <- Getting all services")

        try:
            services = load_services()

            logger.debug("[get_all_services] -> Found %d services", len(services))
            return services

        except Exception as e:
            logger.error("[get_all_services] Error loading services: %s", str(e))
            return []

    async def get_service_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Получение сервиса по коду"""
        logger.debug("[get_service_by_code] <- code='%s'", code)

        try:
            service = get_service_by_code(code)

            if service:
                logger.debug("[get_service_by_code] -> Found service: %s", service.get("name"))
            else:
                logger.warning("[get_service_by_code] -> Service not found for code '%s'", code)

            return service if service else None

        except Exception as e:
            logger.error("[get_service_by_code] Error getting service '%s': %s", code, str(e))
            return None

    async def get_platform_services(self) -> List[Dict[str, Any]]:
        """Получение платформенных сервисов"""
        logger.debug("[get_platform_services] <- Getting platform services")

        try:
            platform_services = get_platform_services()

            logger.debug("[get_platform_services] -> Found %d platform services", len(platform_services))
            return platform_services

        except Exception as e:
            logger.error("[get_platform_services] Error getting platform services: %s", str(e))
            return []

    async def is_platform_service(self, service_code: str) -> bool:
        """Проверка, является ли сервис платформенным"""
        logger.debug("[is_platform_service] <- service_code='%s'", service_code)

        try:
            is_platform = is_platform_service(service_code)

            logger.debug("[is_platform_service] -> is_platform=%s", is_platform)
            return is_platform

        except Exception as e:
            logger.error("[is_platform_service] Error checking service '%s': %s", service_code, str(e))
            return False

    async def service_exists(self, service_code: str) -> bool:
        """Проверка существования сервиса"""
        logger.debug("[service_exists] <- service_code='%s'", service_code)

        try:
            service = await self.get_service_by_code(service_code)
            exists = service is not None

            logger.debug("[service_exists] -> exists=%s", exists)
            return exists

        except Exception as e:
            logger.error("[service_exists] Error checking service existence '%s': %s", service_code, str(e))
            return False