# app/infrastructure/repositories/file_template_repository.py
import logging
from typing import Optional, Dict, List

from app.domain.repositories.template_repository import TemplateRepository
from app.template_registry import store_templates, get_template_by_type, get_all_template_types

logger = logging.getLogger(__name__)


class FileTemplateRepository(TemplateRepository):
    """Реализация репозитория шаблонов через файловое хранилище и векторную БД"""

    async def get_template_by_type(self, requirement_type: str) -> Optional[str]:
        """Получение шаблона по типу требования"""
        logger.debug("[get_template_by_type] <- requirement_type='%s'", requirement_type)

        try:
            template = get_template_by_type(requirement_type)

            if template:
                logger.debug("[get_template_by_type] -> Found template, length: %d", len(template))
            else:
                logger.warning("[get_template_by_type] -> No template found for type '%s'", requirement_type)

            return template

        except Exception as e:
            logger.error("[get_template_by_type] Error getting template for type '%s': %s",
                         requirement_type, str(e))
            return None

    async def save_templates(self, templates: Dict[str, str]) -> int:
        """Сохранение шаблонов"""
        logger.info("[save_templates] <- Saving %d templates", len(templates))

        try:
            saved_count = store_templates(templates)

            logger.info("[save_templates] -> Successfully saved %d templates", saved_count)
            return saved_count

        except Exception as e:
            logger.error("[save_templates] Error saving templates: %s", str(e))
            raise

    async def get_all_template_types(self) -> List[str]:
        """Получение всех доступных типов шаблонов"""
        logger.debug("[get_all_template_types] <- Getting all template types")

        try:
            template_types = get_all_template_types()

            logger.debug("[get_all_template_types] -> Found %d template types", len(template_types))
            return template_types

        except Exception as e:
            logger.error("[get_all_template_types] Error getting template types: %s", str(e))
            return []

    async def delete_template(self, requirement_type: str) -> bool:
        """Удаление шаблона"""
        logger.info("[delete_template] <- requirement_type='%s'", requirement_type)

        try:
            # Пока не реализовано в template_registry, заглушка
            logger.warning("[delete_template] Template deletion not implemented yet")
            return False

        except Exception as e:
            logger.error("[delete_template] Error deleting template '%s': %s", requirement_type, str(e))
            return False