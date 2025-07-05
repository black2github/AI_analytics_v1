# app/services/template_type_analysis.py

import json
import logging
import os
import re
from typing import List, Optional, Dict, Any
from app.confluence_loader import get_page_content_by_id, get_page_title_by_id
from app.filter_all_fragments import filter_all_fragments

logger = logging.getLogger(__name__)

FEATURES_FILE = "features.json"


class TemplateTypeAnalyzer:
    """Анализатор типов шаблонов требований для страниц Confluence"""

    def __init__(self):
        self.features = self._load_features()

    def _load_features(self) -> Dict[str, Any]:
        """Загружает конфигурацию типов шаблонов из features.json"""
        try:
            features_path = os.path.join(os.path.dirname(__file__), "..", "data", FEATURES_FILE)
            with open(features_path, 'r', encoding='utf-8') as f:
                features = json.load(f)
                logger.info("[TemplateTypeAnalyzer] Loaded %d template types from features.json", len(features))
                return features
        except Exception as e:
            logger.error("[TemplateTypeAnalyzer] Failed to load features.json: %s", str(e))
            return {}

    def analyze_page_type(self, page_id: str) -> Optional[str]:
        """
        Определяет тип шаблона для одной страницы Confluence

        Args:
            page_id: Идентификатор страницы

        Returns:
            Название типа шаблона или None если не определен
        """
        logger.info("[analyze_page_type] Analyzing page_id: %s", page_id)

        if not self.features:
            logger.warning("[analyze_page_type] No features loaded, returning None")
            return None

        # Получаем данные страницы
        page_title = get_page_title_by_id(page_id)
        page_html = get_page_content_by_id(page_id, clean_html=False)

        if not page_title or not page_html:
            logger.warning("[analyze_page_type] Failed to load page data for %s", page_id)
            return None

        # Получаем текстовое содержимое страницы
        page_content = filter_all_fragments(page_html)

        logger.debug("[analyze_page_type] Page title: '%s'", page_title)
        logger.debug("[analyze_page_type] Page content length: %d chars", len(page_content))

        # Проверяем каждый тип шаблона
        for template_type, template_config in self.features.items():
            logger.debug("[analyze_page_type] Checking template type: %s", template_type)

            if self._check_template_match(page_title, page_content, template_config):
                logger.info("[analyze_page_type] -> Found match: %s", template_type)
                return template_type

        logger.info("[analyze_page_type] -> No template match found")
        return None

    def analyze_pages_types(self, page_ids: List[str]) -> List[Optional[str]]:
        """
        Определяет типы шаблонов для списка страниц

        Args:
            page_ids: Список идентификаторов страниц

        Returns:
            Список типов шаблонов (или None для каждой страницы)
        """
        logger.info("[analyze_pages_types] Analyzing %d pages", len(page_ids))

        results = []
        for page_id in page_ids:
            try:
                template_type = self.analyze_page_type(page_id)
                results.append(template_type)
            except Exception as e:
                logger.error("[analyze_pages_types] Error analyzing page %s: %s", page_id, str(e))
                results.append(None)

        logger.info("[analyze_pages_types] -> Completed analysis of %d pages", len(results))
        return results

    def _check_template_match(self, page_title: str, page_content: str, template_config: Dict) -> bool:
        """
        Проверяет соответствие страницы шаблону

        Args:
            page_title: Заголовок страницы
            page_content: Содержимое страницы
            template_config: Конфигурация шаблона

        Returns:
            True если страница соответствует шаблону
        """
        # 1. Проверка названия страницы
        if not self._check_title_match(page_title, template_config.get("title")):
            logger.debug("[_check_template_match] Title check failed")
            return False

        # 2. Проверка заголовков
        if not self._check_headers_match(page_content, template_config.get("headers")):
            logger.debug("[_check_template_match] Headers check failed")
            return False

        # 3. Проверка содержимого
        if not self._check_content_match(page_content, template_config.get("content")):
            logger.debug("[_check_template_match] Content check failed")
            return False

        logger.debug("[_check_template_match] All checks passed")
        return True

    def _check_title_match(self, page_title: str, title_synonyms: Optional[List[str]]) -> bool:
        """Проверяет соответствие названия страницы"""
        if title_synonyms is None:
            logger.debug("[_check_title_match] Title check skipped (null)")
            return True

        page_title_lower = page_title.lower()
        for synonym in title_synonyms:
            if synonym.lower() in page_title_lower:
                logger.debug("[_check_title_match] Title match found: '%s' in '%s'", synonym, page_title)
                return True

        logger.debug("[_check_title_match] No title match found")
        return False

    def _check_headers_match(self, page_content: str, headers_config: Optional[List[List[str]]]) -> bool:
        """Проверяет соответствие заголовков страницы"""
        if headers_config is None:
            logger.debug("[_check_headers_match] Headers check skipped (null)")
            return True

        # Извлекаем все заголовки из содержимого
        headers = self._extract_headers(page_content)
        headers_lower = [h.lower() for h in headers]

        logger.debug("[_check_headers_match] Found %d headers: %s", len(headers), headers)

        # Для каждого набора синонимов должен найтись хотя бы один заголовок
        for synonym_group in headers_config:
            group_found = False
            for synonym in synonym_group:
                if any(synonym.lower() in header for header in headers_lower):
                    logger.debug("[_check_headers_match] Header group match: '%s'", synonym)
                    group_found = True
                    break

            if not group_found:
                logger.debug("[_check_headers_match] Header group not found: %s", synonym_group)
                return False

        logger.debug("[_check_headers_match] All header groups matched")
        return True

    def _check_content_match(self, page_content: str, content_config: Optional[List[List[str]]]) -> bool:
        """Проверяет соответствие содержимого страницы"""
        if content_config is None:
            logger.debug("[_check_content_match] Content check skipped (null)")
            return True

        page_content_lower = page_content.lower()

        # Для каждого набора синонимов должен найтись хотя бы один в тексте
        for synonym_group in content_config:
            group_found = False
            for synonym in synonym_group:
                if synonym.lower() in page_content_lower:
                    logger.debug("[_check_content_match] Content group match: '%s'", synonym)
                    group_found = True
                    break

            if not group_found:
                logger.debug("[_check_content_match] Content group not found: %s", synonym_group)
                return False

        logger.debug("[_check_content_match] All content groups matched")
        return True

    def _extract_headers(self, content: str) -> List[str]:
        """
        Извлекает заголовки из markdown содержимого
        Ищет строки, начинающиеся с # (markdown заголовки)
        """
        headers = []
        lines = content.split('\n')

        for line in lines:
            line = line.strip()
            # Markdown заголовки
            if line.startswith('#'):
                # Убираем символы # и пробелы
                header_text = re.sub(r'^#+\s*', '', line).strip()
                if header_text:
                    headers.append(header_text)
            # Также ищем строки с **Заголовок:** (жирный текст)
            elif line.startswith('**') and line.endswith('**'):
                header_text = line.strip('*').strip()
                if header_text:
                    headers.append(header_text)

        return headers


# Глобальный экземпляр анализатора
_analyzer = TemplateTypeAnalyzer()


def analyze_page_template_type(page_id: str) -> Optional[str]:
    """Функция-обертка для анализа одной страницы"""
    return _analyzer.analyze_page_type(page_id)


def analyze_pages_template_types(page_ids: List[str]) -> List[Optional[str]]:
    """Функция-обертка для анализа нескольких страниц"""
    return _analyzer.analyze_pages_types(page_ids)