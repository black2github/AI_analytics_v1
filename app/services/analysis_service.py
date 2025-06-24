# app/services/analysis_service.py
import logging
import json
import re
import time
from typing import Optional, List, Dict, Any
import tiktoken
from langchain_core.prompts import PromptTemplate
from langchain.chains.llm import LLMChain

from app.domain.services.context_builder import ContextBuilder, ContextBuilderError
from app.llm_interface import get_llm
from app.confluence_loader import get_page_content_by_id
from app.service_registry import resolve_service_code_from_pages_or_user, resolve_service_code_by_user
from app.template_registry import get_template_by_type
from app.config import (
    LLM_PROVIDER, PAGE_ANALYSIS_PROMPT_FILE, TEMPLATE_ANALYSIS_PROMPT_FILE, UNIFIED_STORAGE_NAME
)

logger = logging.getLogger(__name__)


class AnalysisServiceError(Exception):
    """Базовое исключение для AnalysisService"""
    pass


class AnalysisService:
    """Сервис для анализа требований с использованием LLM и RAG"""

    def __init__(self):
        self.llm = get_llm()
        self.context_builder = ContextBuilder()
        self._encoding = tiktoken.get_encoding("cl100k_base")

    async def analyze_text(
            self,
            text: str,
            prompt_template: Optional[str] = None,
            service_code: Optional[str] = None
    ) -> str:
        """Анализирует текстовые требования"""
        logger.info("[analyze_text] <- text length=%d, service_code=%s", len(text), service_code)

        try:
            # Определяем код сервиса
            resolved_service_code = service_code
            if not service_code:
                resolved_service_code = resolve_service_code_by_user()
                logger.info("[analyze_text] Resolved service_code: %s", resolved_service_code)

            # Строим контекст
            context = await self.context_builder.build_context(resolved_service_code, requirements_text=text)

            # Создаем цепочку анализа
            chain = self._build_chain(prompt_template)

            # Выполняем анализ
            result = chain.run({"requirement": text, "context": context})

            logger.info("[analyze_text] -> result length=%d", len(result))
            return result

        except ContextBuilderError as e:
            logger.error("[analyze_text] Context building error: %s", str(e))
            raise AnalysisServiceError(f"Failed to build context: {str(e)}")
        except Exception as e:
            if "token limit" in str(e).lower():
                logger.error("[analyze_text] Token limit exceeded: %s", str(e))
                raise AnalysisServiceError("Превышен лимит токенов модели. Уменьшите объем текста или контекста.")
            logger.error("[analyze_text] Unexpected error: %s", str(e))
            raise AnalysisServiceError(f"Analysis failed: {str(e)}")

    async def analyze_pages(
            self,
            page_ids: List[str],
            prompt_template: Optional[str] = None,
            service_code: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Анализирует страницы Confluence"""
        logger.info("[analyze_pages] <- page_ids=%s, service_code=%s", page_ids, service_code)

        try:
            # Определяем код сервиса
            resolved_service_code = service_code
            if not service_code:
                resolved_service_code = resolve_service_code_from_pages_or_user(page_ids)
                logger.debug("[analyze_pages] Resolved service_code: %s", resolved_service_code)

            # Собираем и валидируем страницы
            requirements, valid_page_ids = await self._collect_and_validate_pages(page_ids, prompt_template)

            if not requirements:
                logger.warning("[analyze_pages] No valid requirements found, service code: %s", resolved_service_code)
                return []

            # Формируем текст требований
            requirements_text = "\n\n".join([
                f"Page ID: {req['page_id']}\n{req['content']}" for req in requirements
            ])

            # Строим контекст
            context = await self.context_builder.build_context(
                service_code=resolved_service_code,
                requirements_text=requirements_text,
                exclude_page_ids=page_ids
            )

            # Проверяем лимиты токенов
            context_tokens = self._count_tokens(context)
            max_tokens = 65000
            max_context_tokens = max_tokens // 2

            if context_tokens > max_context_tokens:
                logger.warning("[analyze_pages] Context too large (%d tokens), limiting analysis", context_tokens)
                return [{"page_id": pid, "analysis": "Анализ невозможен: контекст слишком большой"}
                        for pid in valid_page_ids]

            # Создаем цепочку и выполняем анализ
            chain = self._build_chain(prompt_template)

            # Проверяем общий размер промпта
            total_tokens = await self._estimate_total_tokens(chain, requirements_text, context)
            if total_tokens > max_tokens:
                logger.warning("[analyze_pages] Total tokens (%d) exceed limit (%d)", total_tokens, max_tokens)
                return [{"page_id": pid, "analysis": "Анализ невозможен: превышен лимит токенов"}
                        for pid in valid_page_ids]

            # Выполняем анализ
            result = chain.run({"requirement": requirements_text, "context": context})

            # Парсим результат
            return await self._parse_analysis_result(result, valid_page_ids)

        except ContextBuilderError as e:
            logger.error("[analyze_pages] Context building error: %s", str(e))
            raise AnalysisServiceError(f"Failed to build context: {str(e)}")
        except Exception as e:
            if "token limit" in str(e).lower():
                logger.error("[analyze_pages] Token limit exceeded: %s", str(e))
                raise AnalysisServiceError("Превышен лимит токенов модели")
            logger.error("[analyze_pages] Unexpected error: %s", str(e))
            raise AnalysisServiceError(f"Pages analysis failed: {str(e)}")

    async def analyze_with_templates(
            self,
            items: List[dict],
            prompt_template: Optional[str] = None,
            service_code: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Анализирует требования на соответствие шаблонам"""
        logger.info("[analyze_with_templates] <- items count: %d, service_code: %s", len(items), service_code)

        try:
            # Определяем код сервиса
            resolved_service_code = service_code
            if not service_code:
                page_ids = [item["page_id"] for item in items]
                resolved_service_code = resolve_service_code_from_pages_or_user(page_ids)
                logger.info("[analyze_with_templates] Resolved service_code: %s", resolved_service_code)

            results = []
            template_chain = self._build_template_analysis_chain(prompt_template)

            for item in items:
                requirement_type = item["requirement_type"]
                page_id = item["page_id"]

                logger.info("[analyze_with_templates] Processing page_id: %s, type: %s", page_id, requirement_type)

                try:
                    # Получаем контент страницы и шаблон
                    content = get_page_content_by_id(page_id, clean_html=True)
                    template_html = get_template_by_type(requirement_type)

                    if not content or not template_html:
                        logger.warning("[analyze_with_templates] Missing content or template for page %s", page_id)
                        results.append({
                            "page_id": page_id,
                            "requirement_type": requirement_type,
                            "template_analysis": {
                                "error": "Отсутствует содержимое страницы или шаблон",
                                "template_available": bool(template_html),
                                "content_available": bool(content)
                            },
                            "legacy_formatting_issues": []
                        })
                        continue

                    # Строим контекст
                    context = await self.context_builder.build_context(
                        service_code=resolved_service_code,
                        requirements_text=content,
                        exclude_page_ids=[page_id]
                    )

                    # Быстрая структурная проверка (legacy поддержка)
                    legacy_formatting_issues = self._perform_legacy_structure_check(template_html, content)

                    # Анализ через LLM
                    logger.debug(
                        "[analyze_with_templates] Sending to LLM: template=%d chars, content=%d chars, context=%d chars",
                        len(template_html), len(content), len(context))

                    llm_result = template_chain.run({
                        "requirement": content,
                        "template": template_html,
                        "context": context
                    })

                    # Парсим JSON ответ от LLM
                    try:
                        template_analysis = self._parse_llm_template_response(llm_result)
                        logger.info("[analyze_with_templates] LLM analysis completed for page %s", page_id)
                    except Exception as json_error:
                        logger.error("[analyze_with_templates] Failed to parse LLM JSON for page %s: %s",
                                     page_id, str(json_error))
                        template_analysis = {
                            "error": "Не удалось разобрать ответ LLM",
                            "raw_response": llm_result[:500],
                            "parse_error": str(json_error)
                        }

                    results.append({
                        "page_id": page_id,
                        "requirement_type": requirement_type,
                        "template_analysis": template_analysis,
                        "legacy_formatting_issues": legacy_formatting_issues,
                        "template_used": requirement_type,
                        "analysis_timestamp": time.time(),
                        "storage_used": UNIFIED_STORAGE_NAME
                    })

                except Exception as item_error:
                    logger.error("[analyze_with_templates] Error analyzing page %s: %s", page_id, str(item_error))

                    if "token limit" in str(item_error).lower():
                        error_msg = "Превышен лимит токенов модели"
                    else:
                        error_msg = f"Ошибка анализа: {str(item_error)}"

                    results.append({
                        "page_id": page_id,
                        "requirement_type": requirement_type,
                        "template_analysis": {
                            "error": error_msg,
                            "error_type": "llm_error"
                        },
                        "legacy_formatting_issues": []
                    })

            logger.info("[analyze_with_templates] -> Completed analysis for %d items", len(results))
            return results

        except ContextBuilderError as e:
            logger.error("[analyze_with_templates] Context building error: %s", str(e))
            raise AnalysisServiceError(f"Failed to build context: {str(e)}")
        except Exception as e:
            logger.error("[analyze_with_templates] Unexpected error: %s", str(e))
            raise AnalysisServiceError(f"Template analysis failed: {str(e)}")

    # Приватные методы
    def _build_chain(self, prompt_template: Optional[str]) -> LLMChain:
        """Создает цепочку LangChain с заданным шаблоном промпта"""
        logger.info("[_build_chain] <- prompt_template=%s", bool(prompt_template))

        if prompt_template:
            if not all(var in prompt_template for var in ["{requirement}", "{context}"]):
                raise AnalysisServiceError("Prompt template must include {requirement} and {context}")
            prompt = PromptTemplate(input_variables=["requirement", "context"], template=prompt_template)
        else:
            try:
                with open(PAGE_ANALYSIS_PROMPT_FILE, "r", encoding="utf-8") as file:
                    template = file.read().strip()
                if not template:
                    template = "Проанализируй требования: {requirement}\nКонтекст: {context}\nПредоставь детальный анализ."
                prompt = PromptTemplate(
                    input_variables=["requirement", "context"],
                    template=template
                )
            except FileNotFoundError:
                logger.error("[_build_chain] Файл %s не найден", PAGE_ANALYSIS_PROMPT_FILE)
                raise AnalysisServiceError(f"Prompt template file not found: {PAGE_ANALYSIS_PROMPT_FILE}")
            except Exception as e:
                logger.error("[_build_chain] Ошибка чтения %s: %s", PAGE_ANALYSIS_PROMPT_FILE, str(e))
                raise AnalysisServiceError(f"Error reading prompt template: {str(e)}")

        logger.info("[_build_chain] -> prompt template created successfully")
        return LLMChain(llm=self.llm, prompt=prompt)

    def _build_template_analysis_chain(self, custom_prompt: Optional[str] = None) -> LLMChain:
        """Создает цепочку LangChain для анализа соответствия шаблону"""
        logger.info("[_build_template_analysis_chain] <- custom_prompt provided: %s", bool(custom_prompt))

        if custom_prompt:
            required_vars = ["{requirement}", "{template}", "{context}"]
            if not all(var in custom_prompt for var in required_vars):
                raise AnalysisServiceError(f"Custom prompt template must include {required_vars}")
            template = custom_prompt
        else:
            try:
                with open(TEMPLATE_ANALYSIS_PROMPT_FILE, "r", encoding="utf-8") as file:
                    template = file.read().strip()
                if not template:
                    raise AnalysisServiceError("Template analysis prompt file is empty")
            except FileNotFoundError:
                logger.error("[_build_template_analysis_chain] Файл %s не найден", TEMPLATE_ANALYSIS_PROMPT_FILE)
                template = """
Проанализируй соответствие требований шаблону:

ШАБЛОН: {template}
ТРЕБОВАНИЯ: {requirement}
КОНТЕКСТ: {context}

Верни анализ в формате JSON с оценками соответствия, качества и рекомендациями.
"""
            except Exception as e:
                logger.error("[_build_template_analysis_chain] Ошибка чтения %s: %s", TEMPLATE_ANALYSIS_PROMPT_FILE,
                             str(e))
                raise AnalysisServiceError(f"Error reading template prompt: {str(e)}")

        prompt = PromptTemplate(
            input_variables=["requirement", "template", "context"],
            template=template
        )

        logger.info("[_build_template_analysis_chain] -> Template analysis chain created")
        return LLMChain(llm=self.llm, prompt=prompt)

    def _count_tokens(self, text: str) -> int:
        """Подсчитывает количество токенов в тексте"""
        if LLM_PROVIDER == "deepseek":
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        else:
            try:
                return len(self._encoding.encode(text))
            except Exception as e:
                logger.error("[_count_tokens] Error counting tokens: %s", str(e))
                return len(text.split())

    async def _collect_and_validate_pages(self, page_ids: List[str], prompt_template: Optional[str]) -> tuple:
        """Собирает и валидирует страницы для анализа"""
        requirements = []
        valid_page_ids = []
        max_tokens = 65000
        max_context_tokens = max_tokens // 2
        current_tokens = 0

        template = prompt_template or open(PAGE_ANALYSIS_PROMPT_FILE, "r", encoding="utf-8").read().strip()
        template_tokens = self._count_tokens(template)

        # Собираем страницы до превышения лимита токенов
        for page_id in page_ids:
            content = get_page_content_by_id(page_id, clean_html=True)
            if content:
                req_text = f"Page ID: {page_id}\n{content}"
                req_tokens = self._count_tokens(req_text)
                if current_tokens + req_tokens + template_tokens < max_tokens - max_context_tokens:
                    requirements.append({"page_id": page_id, "content": content})
                    valid_page_ids.append(page_id)
                    current_tokens += req_tokens
                else:
                    logger.warning("[_collect_and_validate_pages] Excluded page %s due to token limit", page_id)
                    break

        return requirements, valid_page_ids

    async def _estimate_total_tokens(self, chain: LLMChain, requirements_text: str, context: str) -> int:
        """Оценивает общее количество токенов для промпта"""
        full_prompt = chain.prompt.format(requirement=requirements_text, context=context)
        return self._count_tokens(full_prompt)

    async def _parse_analysis_result(self, result: str, valid_page_ids: List[str]) -> List[Dict[str, Any]]:
        """Парсит результат анализа страниц"""
        logger.debug("[_parse_analysis_result] Raw LLM response: '%s'", result)

        # Извлекаем и парсим JSON
        cleaned_result = self._extract_json_from_llm_response(result)
        if not cleaned_result:
            logger.error("[_parse_analysis_result] No valid JSON found in LLM response")
            return [{"page_id": pid, "analysis": "Ошибка: LLM не вернул корректный JSON"} for pid in valid_page_ids]

        try:
            parsed_result = json.loads(cleaned_result)
            logger.info("[_parse_analysis_result] Successfully parsed JSON response")
        except json.JSONDecodeError as json_err:
            logger.error("[_parse_analysis_result] JSON decode error: %s", str(json_err))
            return [{"page_id": valid_page_ids[0] if valid_page_ids else "unknown", "analysis": result}]

        if not isinstance(parsed_result, dict):
            logger.error("[_parse_analysis_result] Result is not a dictionary")
            return [{"page_id": pid, "analysis": "Ошибка: неожиданный формат ответа LLM"} for pid in valid_page_ids]

        results = []
        logger.debug("[_parse_analysis_result] results: '%s'", parsed_result)
        for page_id in valid_page_ids:
            analysis = parsed_result.get(page_id, f"Анализ для страницы {page_id} не найден")
            results.append({"page_id": page_id, "analysis": analysis})

        logger.info("[_parse_analysis_result] -> Result count: %d", len(results))
        return results

    def _extract_json_from_llm_response(self, response: str) -> Optional[str]:
        """Извлекает JSON из ответа LLM, удаляя лишний текст и форматирование"""
        if not response:
            return None

        # Убираем markdown форматирование
        response = response.strip()
        response = response.strip("```json").strip("```").strip()

        json_patterns = [
            # 1. Жадный поиск JSON в markdown блоке
            r'```json\s*(\{.*\})\s*```',
            # 2. Простой поиск от первой { до последней } (жадный)
            r'(\{.*\})',
            # 3. Поиск сбалансированных скобок (как fallback)
            r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})',
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, response, re.DOTALL | re.MULTILINE)
            for match in matches:
                try:
                    # Проверяем, что это валидный JSON
                    json.loads(match)
                    logger.debug("[_extract_json_from_llm_response] Found valid JSON with pattern: %s", pattern)
                    return match.strip()
                except json.JSONDecodeError:
                    continue

        # Если ничего не найдено, пробуем найти JSON вручную
        try:
            # Ищем первую открывающую скобку
            start = response.find('{')
            if start == -1:
                return None

            # Ищем соответствующую закрывающую скобку
            brace_count = 0
            end = start

            for i, char in enumerate(response[start:], start):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i
                        break

            if brace_count == 0:
                candidate = response[start:end + 1]
                # Проверяем валидность
                json.loads(candidate)
                logger.debug("[_extract_json_from_llm_response] Found valid JSON by manual parsing")
                return candidate.strip()

        except (json.JSONDecodeError, ValueError):
            pass

        logger.warning("[_extract_json_from_llm_response] No valid JSON found in response")
        return None

    def _perform_legacy_structure_check(self, template_html: str, content: str) -> List[str]:
        """Выполняет быструю структурную проверку (legacy код для обратной совместимости)"""
        try:
            from markdownify import markdownify
            from bs4 import BeautifulSoup

            template_md = markdownify(template_html, heading_style="ATX")
            content_md = markdownify(content, heading_style="ATX")
            template_soup = BeautifulSoup(template_md, 'html.parser')
            content_soup = BeautifulSoup(content_md, 'html.parser')

            formatting_issues = []

            # Проверка заголовков
            template_headers = [h.get_text().strip() for h in template_soup.find_all(['h1', 'h2', 'h3'])]
            content_headers = [h.get_text().strip() for h in content_soup.find_all(['h1', 'h2', 'h3'])]
            if set(template_headers) != set(content_headers):
                formatting_issues.append(
                    f"Несоответствие заголовков: ожидаются {template_headers}, найдены {content_headers}")

            # Проверка таблиц
            template_tables = template_soup.find_all('table')
            content_tables = content_soup.find_all('table')
            if len(template_tables) != len(content_tables):
                formatting_issues.append(
                    f"Несоответствие количества таблиц: ожидается {len(template_tables)}, найдено {len(content_tables)}")

            return formatting_issues

        except Exception as e:
            logger.warning("[_perform_legacy_structure_check] Error in legacy check: %s", str(e))
            return [f"Ошибка структурной проверки: {str(e)}"]

    def _parse_llm_template_response(self, llm_response: str) -> dict:
        """Парсит JSON ответ от LLM"""
        json_content = self._extract_json_from_llm_response(llm_response)

        if not json_content:
            raise ValueError("No valid JSON found in LLM response")

        parsed_result = json.loads(json_content)

        # Валидируем структуру ответа
        required_sections = ["template_compliance", "content_quality", "system_integration", "recommendations",
                             "summary"]
        missing_sections = [section for section in required_sections if section not in parsed_result]

        if missing_sections:
            logger.warning("[_parse_llm_template_response] Missing sections in LLM response: %s", missing_sections)
            for section in missing_sections:
                parsed_result[section] = {"error": f"Section {section} missing from LLM response"}

        return parsed_result