# app/services/analysis_service.py

import json
import logging
import re
import time
from typing import Optional, List
from langchain_core.prompts import PromptTemplate
from app.config import PAGE_ANALYSIS_PROMPT_FILE, UNIFIED_STORAGE_NAME
from app.confluence_loader import get_page_content_by_id
from app.rag_pipeline import logger, build_chain, count_tokens, build_template_analysis_chain, _perform_legacy_structure_check
from app.service_registry import resolve_service_code_by_user, resolve_service_code_from_pages_or_user
from app.services.context_builder import build_context
from app.template_registry import get_template_by_type


def analyze_text(text: str, prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    logger.info("[analyze_text] <- text length=%d, service_code=%s", len(text), service_code)
    if not service_code:
        service_code = resolve_service_code_by_user()
        logger.info("[analyze_text] Resolved service_code: %s", service_code)

    chain = build_chain(prompt_template)
    context = build_context(service_code, requirements_text=text)

    try:
        result = chain.run({"requirement": text, "context": context})
        logger.info("[analyze_text] -> result length=%d", len(result))
        return result
    except Exception as e:
        if "token limit" in str(e).lower():
            logger.error("[analyze_text] Token limit exceeded: %s", str(e))
            return {"error": "Превышен лимит токенов модели. Уменьшите объем текста или контекста."}
        raise


def analyze_pages(page_ids: List[str], prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    logger.info("[analyze_pages] <- page_ids=%s, service_code=%s", page_ids, service_code)
    try:
        if not service_code:
            service_code = resolve_service_code_from_pages_or_user(page_ids)
            logger.debug("[analyze_pages] Resolved service_code: %s", service_code)

        requirements = []
        valid_page_ids = []
        max_tokens = 65000
        max_context_tokens = max_tokens // 2
        current_tokens = 0
        template = prompt_template or open(PAGE_ANALYSIS_PROMPT_FILE, "r", encoding="utf-8").read().strip()
        template_tokens = count_tokens(template)

        # Собираем страницы до превышения лимита токенов
        for page_id in page_ids:
            content = get_page_content_by_id(page_id, clean_html=True)
            if content:
                req_text = f"Page ID: {page_id}\n{content}"
                req_tokens = count_tokens(req_text)
                if current_tokens + req_tokens + template_tokens < max_tokens - max_context_tokens:
                    requirements.append({"page_id": page_id, "content": content})
                    valid_page_ids.append(page_id)
                    current_tokens += req_tokens
                else:
                    logging.warning("[analyze_pages] Excluded page %s due to token limit", page_id)
                    break

        if not requirements:
            logging.warning("[analyze_pages] No valid requirements found, service code: %s", service_code)
            return []

        requirements_text = "\n\n".join(
            [f"Page ID: {req['page_id']}\n{req['content']}" for req in requirements]
        )

        # Используем новую функцию построения контекста
        context = build_context(service_code, requirements_text=requirements_text, exclude_page_ids=page_ids)

        context_tokens = count_tokens(context)
        if context_tokens > max_context_tokens:
            logging.warning("[analyze_pages] Context too large (%d tokens), limiting analysis", context_tokens)
            return [{"page_id": pid, "analysis": "Анализ невозможен: контекст слишком большой"} for pid in
                    valid_page_ids]
            # return [{"Страница №": pid, "Анализ": "Анализ невозможен: контекст слишком большой"} for pid in
            #         valid_page_ids]

        # Проверяем общий размер
        full_prompt = PromptTemplate(
            input_variables=["requirement", "context"],
            template=template
        ).format(requirement=requirements_text, context=context)
        total_tokens = count_tokens(full_prompt)

        logger.debug("[analyze_pages] Tokens: requirements=%d, context=%d, total=%d",
                     current_tokens, context_tokens, total_tokens)

        if total_tokens > max_tokens:
            logging.warning("[analyze_pages] Total tokens (%d) exceed limit (%d)", total_tokens, max_tokens)
            return [{"page_id": pid, "analysis": "Анализ невозможен: превышен лимит токенов"} for pid in valid_page_ids]
            # return [{"Страница №": pid, "Анализ": "Анализ невозможен: превышен лимит токенов"} for pid in valid_page_ids]

        chain = build_chain(prompt_template)
        try:
            result = chain.run({"requirement": requirements_text, "context": context})
            logger.debug("[analyze_pages] Raw LLM response: '%s'", result)

            # Извлекаем и парсим JSON
            cleaned_result = _extract_json_from_llm_response(result)
            if not cleaned_result:
                logger.error("[analyze_pages] No valid JSON found in LLM response")
                return [{"page_id": pid, "analysis": "Ошибка: LLM не вернул корректный JSON"} for pid in valid_page_ids]
                # return [{"Страница №": pid, "Анализ": "Ошибка: LLM не вернул корректный JSON"} for pid in valid_page_ids]

            try:
                parsed_result = json.loads(cleaned_result)
                logger.info("[analyze_pages] Successfully parsed JSON response")
            except json.JSONDecodeError as json_err:
                logger.error("[analyze_pages] JSON decode error: %s", str(json_err))
                return [{"page_id": valid_page_ids[0] if valid_page_ids else "unknown", "analysis": result}]

            if not isinstance(parsed_result, dict):
                logger.error("[analyze_pages] Result is not a dictionary")
                return [{"page_id": pid, "analysis": "Ошибка: неожиданный формат ответа LLM"} for pid in valid_page_ids]
                # return [{"Страница №": pid, "Анализ": "Ошибка: неожиданный формат ответа LLM"} for pid in valid_page_ids]

            results = []
            logger.debug("[analyze_pages] results: '%s'", parsed_result)
            for page_id in valid_page_ids:
                analysis = parsed_result.get(page_id, f"Анализ для страницы {page_id} не найден")
                results.append({"page_id": page_id, "analysis": analysis})
                # results.append({"Страница №": page_id, "Анализ": analysis})

            logger.info("[analyze_pages] -> Result count: %d", len(results))
            return results

        except Exception as e:
            if "token limit" in str(e).lower():
                logger.error("[analyze_pages] Token limit exceeded: %s", str(e))
                return [{"page_id": pid, "analysis": "Ошибка: превышен лимит токенов модели"} for pid in valid_page_ids]
                # return [{"Страница №": pid, "Анализ": "Ошибка: превышен лимит токенов модели"} for pid in valid_page_ids]
            logger.error("[analyze_pages] Error in LLM chain: %s", str(e))
            raise
    except Exception as e:
        logging.exception("[analyze_pages] Error in analyze_pages")
        raise


def analyze_with_templates(items: List[dict], prompt_template: Optional[str] = None,
                           service_code: Optional[str] = None):
    """
    Анализирует новые требования и их соответствие шаблонам с передачей шаблона в LLM.
    Обновлено для работы с единым хранилищем.
    """
    logger.info("[analyze_with_templates] <- items count: %d, service_code: %s", len(items), service_code)

    if not service_code:
        page_ids = [item["page_id"] for item in items]
        service_code = resolve_service_code_from_pages_or_user(page_ids)
        logger.info("[analyze_with_templates] Resolved service_code: %s", service_code)

    results = []
    template_chain = build_template_analysis_chain(prompt_template)

    for item in items:
        requirement_type = item["requirement_type"]
        page_id = item["page_id"]

        logger.info("[analyze_with_templates] Processing page_id: %s, type: %s", page_id, requirement_type)

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

        template_content = template_html

        # Строим контекст с использованием единого хранилища
        context = build_context(
            service_code=service_code,
            requirements_text=content,
            exclude_page_ids=[page_id]
        )

        # Быстрая структурная проверка (legacy поддержка)
        legacy_formatting_issues = _perform_legacy_structure_check(template_html, content)

        try:
            logger.debug(
                "[analyze_with_templates] Sending to LLM: template=%d chars, content=%d chars, context=%d chars",
                len(template_content), len(content), len(context))

            llm_result = template_chain.run({
                "requirement": content,
                "template": template_content,
                "context": context
            })

            # Парсим JSON ответ от LLM
            try:
                template_analysis = _parse_llm_template_response(llm_result)
                logger.info("[analyze_with_templates] LLM analysis completed for page %s", page_id)
            except Exception as json_error:
                logger.error("[analyze_with_templates] Failed to parse LLM JSON for page %s: %s", page_id,
                             str(json_error))
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

        except Exception as e:
            logger.error("[analyze_with_templates] Error analyzing page %s: %s", page_id, str(e))

            if "token limit" in str(e).lower():
                error_msg = "Превышен лимит токенов модели"
            else:
                error_msg = f"Ошибка анализа: {str(e)}"

            results.append({
                "page_id": page_id,
                "requirement_type": requirement_type,
                "template_analysis": {
                    "error": error_msg,
                    "error_type": "llm_error"
                },
                "legacy_formatting_issues": legacy_formatting_issues
            })

    logger.info("[analyze_with_templates] -> Completed analysis for %d items", len(results))
    return results


def _extract_json_from_llm_response(response: str) -> Optional[str]:
    """
    Извлекает JSON из ответа LLM, удаляя лишний текст и форматирование.
    """
    if not response:
        return None

    # Убираем markdown форматирование
    response = response.strip()
    response = response.strip("```json").strip("```").strip()

    # ИСПРАВЛЕНИЕ: Исправляем порядок и жадность паттернов
    json_patterns = [
        # 1. ИСПРАВЛЕНО: Жадный поиск JSON в markdown блоке
        r'```json\s*(\{.*\})\s*```',  # БЫЛО: (\{.*?\}) - СТАЛО: (\{.*\})
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

    logging.warning("[_extract_json_from_llm_response] No valid JSON found in response")
    return None


def _parse_llm_template_response(llm_response: str) -> dict:
    """Парсит JSON ответ от LLM"""
    json_content = _extract_json_from_llm_response(llm_response)

    if not json_content:
        raise ValueError("No valid JSON found in LLM response")

    parsed_result = json.loads(json_content)

    # Валидируем структуру ответа
    required_sections = ["template_compliance", "content_quality", "system_integration", "recommendations", "summary"]
    missing_sections = [section for section in required_sections if section not in parsed_result]

    if missing_sections:
        logger.warning("[_parse_llm_template_response] Missing sections in LLM response: %s", missing_sections)
        for section in missing_sections:
            parsed_result[section] = {"error": f"Section {section} missing from LLM response"}

    return parsed_result
