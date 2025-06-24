# app/domain/services/context_builder.py
import logging
from typing import List, Optional, Dict, Any
from langchain_core.documents import Document

from app.embedding_store import get_vectorstore
from app.llm_interface import get_embeddings_model
from app.semantic_search import (
    extract_entity_names_from_requirements,
    unified_search_by_entity_title,
    extract_key_queries,
    extract_entity_attribute_queries
)
from app.service_registry import get_platform_services
from app.confluence_loader import get_page_content_by_id, extract_approved_fragments
from app.config import UNIFIED_STORAGE_NAME
from app.style_utils import has_colored_style
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ContextBuilderError(Exception):
    """Исключение для ошибок построения контекста"""
    pass


class ContextBuilder:
    """Сервис для построения контекста для анализа требований"""

    def __init__(self):
        self.embeddings_model = get_embeddings_model()
        self.storage_name = UNIFIED_STORAGE_NAME

    async def build_context(
            self,
            service_code: str,
            requirements_text: str = "",
            exclude_page_ids: Optional[List[str]] = None
    ) -> str:
        """
        Формирование контекста с использованием единого хранилища.

        Args:
            service_code: Код сервиса
            requirements_text: Текст анализируемых требований для семантического поиска
            exclude_page_ids: Список ID страниц, исключаемых из контекста

        Returns:
            Строковый контекст, объединяющий содержимое документов
        """
        logger.info("[build_context] <- service_code=%s, requirements_length=%d, exclude_pages=%d",
                    service_code, len(requirements_text), len(exclude_page_ids or []))

        try:
            # 1. Извлекаем названия сущностей для точного поиска по title
            entity_names = extract_entity_names_from_requirements(requirements_text)

            # 2. Точный поиск документов по названиям сущностей (приоритет #1)
            exact_match_docs = await self._search_by_entity_title(
                entity_names, service_code, exclude_page_ids
            )

            # 3. Извлекаем ключевые запросы
            search_queries = self._prepare_search_queries(requirements_text)
            entity_queries = extract_entity_attribute_queries(requirements_text)
            regular_queries = [q for q in search_queries if q not in entity_queries]

            # 4. Поиск по требованиям текущего сервиса
            service_docs = await self._unified_service_search(
                queries=regular_queries,
                service_code=service_code,
                exclude_page_ids=exclude_page_ids,
                k_per_query=3
            )

            # 5. Поиск по платформенным требованиям
            platform_docs = await self._unified_platform_search(
                queries=regular_queries,
                exclude_page_ids=exclude_page_ids,
                k_per_query=2,
                exclude_services=["dataModel"]  # Исключаем dataModel, так как искали точно на шаге 2
            )

            # 6. Контекст из ссылок
            linked_docs = await self._extract_linked_context_optimized(exclude_page_ids) if exclude_page_ids else []

            # 7. Объединяем все документы (приоритет у точных совпадений)
            all_docs = exact_match_docs + service_docs + platform_docs
            unique_docs = self._fast_deduplicate_documents(all_docs)

            # 8. Формируем контекст
            context_parts = [d.page_content for d in unique_docs] + linked_docs
            context = "\n\n".join(context_parts)
            context = self._smart_truncate_context(context, max_length=16000)

            logger.info("[build_context] -> exact_matches=%d, service=%d, platform=%d, linked=%d",
                        len(exact_match_docs), len(service_docs), len(platform_docs), len(linked_docs))

            return context

        except Exception as e:
            logger.error("[build_context] Error building context: %s", str(e))
            raise ContextBuilderError(f"Failed to build context: {str(e)}")

    # Приватные методы для построения контекста
    async def _search_by_entity_title(
            self,
            entity_names: List[str],
            service_code: str,
            exclude_page_ids: Optional[List[str]]
    ) -> List[Document]:
        """Поиск документов по точному совпадению title с именем сущности"""
        if not entity_names:
            return []

        return unified_search_by_entity_title(
            entity_names, service_code, exclude_page_ids, self.embeddings_model
        )

    async def _unified_service_search(
            self,
            queries: List[str],
            service_code: str,
            exclude_page_ids: Optional[List[str]],
            k_per_query: int
    ) -> List[Document]:
        """Поиск требований конкретного сервиса в едином хранилище"""
        logger.debug("[_unified_service_search] <- %d queries for service_code='%s'", len(queries), service_code)

        store = get_vectorstore(self.storage_name, embedding_model=self.embeddings_model)
        all_docs = []

        # Создаем базовый фильтр для конкретного сервиса
        base_filter = {
            "$and": [
                {"doc_type": {"$eq": "requirement"}},
                {"service_code": {"$eq": service_code}}
            ]
        }

        # Добавляем исключение страниц если нужно
        if exclude_page_ids:
            base_filter["$and"].append({"page_id": {"$nin": exclude_page_ids}})

        logger.debug("[_unified_service_search] Using filter: %s", base_filter)

        for query in queries:
            try:
                docs = store.similarity_search(query, k=k_per_query, filter=base_filter)
                all_docs.extend(docs)
                logger.debug("[_unified_service_search] Query '%s' found %d docs for service %s",
                             query[:50], len(docs), service_code)
            except Exception as e:
                logger.error("[_unified_service_search] Error searching '%s': %s", query[:50], str(e))

        logger.debug("[_unified_service_search] -> %d total docs found", len(all_docs))
        return all_docs

    async def _unified_platform_search(
            self,
            queries: List[str],
            exclude_page_ids: Optional[List[str]],
            k_per_query: int,
            exclude_services: Optional[List[str]] = None
    ) -> List[Document]:
        """Поиск платформенных требований в едином хранилище"""
        logger.debug("[_unified_platform_search] <- %d queries, exclude_services=%s", len(queries), exclude_services)

        store = get_vectorstore(self.storage_name, embedding_model=self.embeddings_model)
        all_docs = []

        # Получаем список платформенных сервисов
        platform_services = get_platform_services()
        if not platform_services:
            logger.warning("[_unified_platform_search] No platform services found")
            return []

        # Исключаем сервисы если нужно
        platform_codes = [svc["code"] for svc in platform_services]
        if exclude_services:
            platform_codes = [code for code in platform_codes if code not in exclude_services]
            logger.debug("[_unified_platform_search] Excluded services: %s", exclude_services)

        if not platform_codes:
            logger.warning("[_unified_platform_search] No platform services left after exclusions")
            return []

        # Создаем фильтр для платформенных требований
        base_filter = {
            "$and": [
                {"doc_type": {"$eq": "requirement"}},
                {"is_platform": {"$eq": True}},
                {"service_code": {"$in": platform_codes}}
            ]
        }

        # Добавляем исключение страниц если нужно
        if exclude_page_ids:
            base_filter["$and"].append({"page_id": {"$nin": exclude_page_ids}})

        logger.debug("[_unified_platform_search] Using filter: %s", base_filter)

        for query in queries:
            try:
                docs = store.similarity_search(query, k=k_per_query * len(platform_codes), filter=base_filter)

                # Ограничиваем результат
                docs = docs[:k_per_query * len(platform_codes)]
                all_docs.extend(docs)

                logger.debug("[_unified_platform_search] Query '%s' found %d platform docs", query[:50], len(docs))
            except Exception as e:
                logger.error("[_unified_platform_search] Error searching '%s': %s", query[:50], str(e))

                # Fallback: поиск без фильтра по service_code
                try:
                    fallback_filter = {
                        "$and": [
                            {"doc_type": {"$eq": "requirement"}},
                            {"is_platform": {"$eq": True}}
                        ]
                    }
                    if exclude_page_ids:
                        fallback_filter["$and"].append({"page_id": {"$nin": exclude_page_ids}})

                    docs = store.similarity_search(query, k=k_per_query, filter=fallback_filter)
                    all_docs.extend(docs)
                    logger.debug("[_unified_platform_search] Fallback found %d docs", len(docs))
                except Exception as e2:
                    logger.error("[_unified_platform_search] Fallback also failed: %s", str(e2))

        logger.info("[_unified_platform_search] -> %d platform docs found", len(all_docs))
        return all_docs

    def _prepare_search_queries(self, requirements_text: str) -> List[str]:
        """Формирует запросы для поиска"""
        if not requirements_text.strip():
            return [""]

        # Извлекаем ключевые запросы
        key_queries = extract_key_queries(requirements_text)

        if key_queries:
            logger.debug("[_prepare_search_queries] -> Using %d key queries", len(key_queries))
            return key_queries

        # Fallback: если ничего не нашли - берем первые 10 слов
        fallback_query = " ".join(requirements_text.split()[:10])
        logger.warning("[_prepare_search_queries] -> Using fallback query: %s", fallback_query)
        return [fallback_query]

    def _fast_deduplicate_documents(self, docs: List[Document]) -> List[Document]:
        """Быстрая дедупликация документов"""
        seen_composite_keys = set()
        unique_docs = []

        for doc in docs:
            page_id = doc.metadata.get('page_id')
            content_hash = hash(doc.page_content[:100])

            composite_key = (page_id, content_hash)
            if composite_key not in seen_composite_keys:
                seen_composite_keys.add(composite_key)
                unique_docs.append(doc)

        logger.debug("[_fast_deduplicate_documents] Deduplicated %d -> %d documents", len(docs), len(unique_docs))
        return unique_docs

    def _smart_truncate_context(self, context: str, max_length: int) -> str:
        """Умное обрезание контекста по границам предложений"""
        if len(context) <= max_length:
            return context

        truncated = context[:max_length]
        last_period = truncated.rfind('.')
        if last_period > max_length * 0.8:
            truncated = truncated[:last_period + 1]

        logger.debug("[_smart_truncate_context] Truncated context from %d to %d chars", len(context), len(truncated))
        return truncated

    async def _extract_linked_context_optimized(self, exclude_page_ids: List[str]) -> List[str]:
        """Извлечение контекста по ссылкам ТОЛЬКО из неподтвержденных (цветных) фрагментов"""
        logger.info("[_extract_linked_context_optimized] <- Processing %d pages for links", len(exclude_page_ids))

        if not exclude_page_ids:
            return []

        linked_docs = []
        max_linked_pages = 3
        max_pages = 5

        for page_id in exclude_page_ids[:max_pages]:
            try:
                content = get_page_content_by_id(page_id, clean_html=False)
                if not content:
                    continue

                # Ищем ссылки ТОЛЬКО в неподтвержденных фрагментах
                linked_page_ids = self._extract_links_from_unconfirmed_fragments(content, exclude_page_ids)
                logger.debug("[_extract_linked_context_optimized] Found %d links in unconfirmed fragments",
                             len(linked_page_ids))

                for linked_page_id in linked_page_ids[:2]:
                    if len(linked_docs) >= max_linked_pages:
                        break

                    linked_content = self._get_approved_content_cached(linked_page_id)
                    if linked_content and linked_content.strip():
                        linked_docs.append(linked_content)
                        logger.debug("[_extract_linked_context_optimized] Added content from linked page '%s'",
                                     linked_page_id)

                if len(linked_docs) >= max_linked_pages:
                    break

            except Exception as e:
                logger.error("[_extract_linked_context_optimized] Error processing page_id=%s: %s", page_id, str(e))

        logger.info("[_extract_linked_context_optimized] -> Found %d linked documents", len(linked_docs))
        return linked_docs

    def _extract_links_from_unconfirmed_fragments(self, html_content: str, exclude_page_ids: List[str]) -> List[str]:
        """Извлекает ссылки ТОЛЬКО из неподтвержденных (цветных) фрагментов требований"""
        soup = BeautifulSoup(html_content, 'html.parser')
        found_page_ids = set()
        exclude_set = set(exclude_page_ids)

        for element in soup.find_all(["p", "li", "span", "div", "td", "th"]):
            if not has_colored_style(element):
                continue

            element_links = self._extract_confluence_links_from_element(element)
            for linked_page_id in element_links:
                if linked_page_id not in exclude_set and linked_page_id not in found_page_ids:
                    found_page_ids.add(linked_page_id)

        return list(found_page_ids)

    def _extract_confluence_links_from_element(self, element) -> List[str]:
        """Извлекает все ссылки на страницы Confluence из конкретного элемента"""
        import re
        page_ids = []

        # 1. Обычные HTML ссылки с pageId в URL
        for link in element.find_all('a', href=True):
            href = link['href']
            patterns = [
                r'pageId=(\d+)',
                r'/pages/viewpage\.action\?pageId=(\d+)',
                r'/display/[^/]+/[^?]*\?pageId=(\d+)',
                r'/wiki/spaces/[^/]+/pages/(\d+)/'
            ]

            for pattern in patterns:
                match = re.search(pattern, href)
                if match:
                    page_ids.append(match.group(1))
                    break

        # 2. Confluence макросы ссылок
        for ac_link in element.find_all('ac:link'):
            ri_page = ac_link.find('ri:page')
            if ri_page:
                page_id = ri_page.get('ri:content-id')
                if page_id:
                    page_ids.append(page_id)

        # 3. Прямые ri:page теги
        for ri_page in element.find_all('ri:page'):
            page_id = ri_page.get('ri:content-id')
            if page_id:
                page_ids.append(page_id)

        return list(set(page_ids))

    def _get_approved_content_cached(self, page_id: str) -> Optional[str]:
        """Кешированное получение подтвержденного контента"""
        try:
            html_content = get_page_content_by_id(page_id, clean_html=False)
            if html_content:
                approved_content = extract_approved_fragments(html_content)
                return approved_content.strip() if approved_content else None
        except Exception as e:
            logger.error("[_get_approved_content_cached] Error loading page_id=%s: %s", page_id, str(e))
        return None