# app/services/analysis_service.py

import json
import logging
import re
import time
from typing import Optional, List
from langchain_core.prompts import PromptTemplate
from app.config import PAGE_ANALYSIS_PROMPT_FILE, UNIFIED_STORAGE_NAME
from app.confluence_loader import get_page_content_by_id
from app.rag_pipeline import logger, build_chain, count_tokens, build_template_analysis_chain
from app.services.template_type_analysis import perform_legacy_structure_check
from app.service_registry import resolve_service_code_by_user, resolve_service_code_from_pages_or_user
from app.services.context_builder import build_context, build_context_optimized
from app.template_registry import get_template_by_type


def analyze_text(text: str, prompt_template: Optional[str] = None, service_code: Optional[str] = None):
    logger.info("[analyze_text] <- text length=%d, service_code=%s", len(text), service_code)
    if not service_code:
        service_code = resolve_service_code_by_user()
        logger.info("[analyze_text] Resolved service_code: %s", service_code)

    chain = build_chain(prompt_template)
    # context = build_context(service_code, requirements_text=text)
    context = build_context_optimized(service_code, requirements_text=text)

    try:
        result = chain.run({"requirement": text, "context": context})
        logger.info("[analyze_text] -> result length=%d", len(result))
        return result
    except Exception as e:
        if "token limit" in str(e).lower():
            logger.error("[analyze_text] Token limit exceeded: %s", str(e))
            return {"error": "Превышен лимит токенов модели. Уменьшите объем текста или контекста."}
        raise


def analyze_pages(page_ids: List[str], prompt_template: Optional[str] = None,
                  service_code: Optional[str] = None, check_templates: bool = False):
    """
    Анализ страниц с опциональной проверкой соответствия шаблонам
    """
    logger.info("[analyze_pages] <- page_ids=%s, service_code=%s, check_templates=%s",
                page_ids, service_code, check_templates)

    try:
        if not service_code:
            service_code = resolve_service_code_from_pages_or_user(page_ids)
            logger.debug("[analyze_pages] Resolved service_code: %s", service_code)

        # ДОБАВЛЯЕМ ИМПОРТЫ
        from app.page_cache import get_page_data_cached
        from app.services.template_type_analysis import get_template_name_by_type

        requirements = []
        valid_page_ids = []
        max_tokens = 128000    # 65000
        max_context_tokens = max_tokens // 2
        current_tokens = 0
        template = prompt_template or open(PAGE_ANALYSIS_PROMPT_FILE, "r", encoding="utf-8").read().strip()
        template_tokens = count_tokens(template)

        #
        # Формируем состав анализируемых требований с заголовками
        #
        for page_id in page_ids:
            # ИЗМЕНЕНО: Используем кешированную функцию для получения всех данных
            page_data = get_page_data_cached(page_id)

            if not page_data:
                logging.warning("[analyze_pages] Could not load page data for %s", page_id)
                continue

            content = page_data['full_content']
            title = page_data['title']
            requirement_type_code = page_data['requirement_type']

            # Получаем человекочитаемое название типа
            requirement_type_name = get_template_name_by_type(
                requirement_type_code) if requirement_type_code else "Неизвестный тип"

            # ИЗМЕНЕНО: Формируем текст с заголовком
            header = f"---\npage_id: {page_id}\ntitle: {title}\ntype: {requirement_type_name}\n---\n"
            page_text_with_header = header + content

            if content:
                req_tokens = count_tokens(page_text_with_header)
                if current_tokens + req_tokens + template_tokens < max_tokens - max_context_tokens:
                    requirements.append({
                        "page_id": page_id,
                        "content": page_text_with_header,
                        "title": title,
                        "requirement_type": requirement_type_name
                    })
                    valid_page_ids.append(page_id)
                    current_tokens += req_tokens
                else:
                    logging.warning("[analyze_pages] Excluded page %s due to token limit", page_id)
                    break

        if not requirements:
            logging.warning("[analyze_pages] No valid requirements found, service code: %s", service_code)
            return []

        # ИЗМЕНЕНО: Формируем requirements_text с заголовками (убираем дублирующий Page ID)
        requirements_text = "\n\n".join([req['content'] for req in requirements])
        logger.debug("[analyze_pages] Resolved requirements with headers: '%s'", requirements_text)

        # Остальной код остается без изменений...
        context = build_context_optimized(service_code, requirements_text=requirements_text, exclude_page_ids=page_ids)

        context_tokens = count_tokens(context)
        if context_tokens > max_context_tokens:
            logging.warning("[analyze_pages] Context too large (%d tokens), limiting analysis", context_tokens)
            return [{"page_id": pid, "analysis": "Анализ невозможен: контекст слишком большой"} for pid in
                    valid_page_ids]

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

        # Основной анализ требований - остается без изменений
        chain = build_chain(prompt_template)
        try:

            result = chain.run({"requirement": requirements_text, "context": context})
            logger.debug("[analyze_pages] Raw LLM response: '%s'", result)

            # Остальной код парсинга результата остается без изменений...
            cleaned_result = _extract_json_from_llm_response(result)
            if not cleaned_result:
                logger.error("[analyze_pages] No valid JSON found in LLM response")
                return [{"page_id": pid, "analysis": "Ошибка: LLM не вернул корректный JSON"} for pid in valid_page_ids]

            try:
                parsed_result = json.loads(cleaned_result)
                logger.info("[analyze_pages] Successfully parsed JSON response")
            except json.JSONDecodeError as json_err:
                logger.error("[analyze_pages] JSON decode error: %s", str(json_err))
                return [{"page_id": valid_page_ids[0] if valid_page_ids else "unknown", "analysis": result}]

            if not isinstance(parsed_result, dict):
                logger.error("[analyze_pages] Result is not a dictionary")
                return [{"page_id": pid, "analysis": "Ошибка: неожиданный формат ответа LLM"} for pid in valid_page_ids]

            results = []
            logger.debug("[analyze_pages] results: '%s'", parsed_result)

            for page_id in valid_page_ids:
                analysis = parsed_result.get(page_id, f"Анализ для страницы {page_id} не найден")
                page_result = {"page_id": page_id, "analysis": analysis}

                if check_templates:
                    template_analysis = _analyze_page_template_if_needed(page_id, service_code)
                    if template_analysis:
                        page_result["template_analysis"] = template_analysis

                results.append(page_result)

            logger.info("[analyze_pages] -> Result count: %d", len(results))
            return results

        except Exception as e:
            if "token limit" in str(e).lower():
                logger.error("[analyze_pages] Token limit exceeded: %s", str(e))
                return [{"page_id": pid, "analysis": "Ошибка: превышен лимит токенов модели"} for pid in valid_page_ids]
            logger.error("[analyze_pages] Error in LLM chain: %s", str(e))
            raise
    except Exception as e:
        logging.exception("[analyze_pages] Error in analyze_pages")
        raise


def _analyze_page_template_if_needed(page_id: str, service_code: str) -> Optional[dict]:
    """
    Анализирует соответствие шаблону (для случая, если страница еще не была одобрена и сохранена)

    Args:
        page_id: Идентификатор страницы
        service_code: Код сервиса

    Returns:
        Результат анализа шаблона или None
    """
    logger.info("[_analyze_page_template_if_needed] <- Checking page_id: %s", page_id)

    try:
        # Импортируем нужные модули
        from app.services.document_service import DocumentService
        from app.services.template_type_analysis import analyze_page_template_type

        # Проверяем наличие одобренных фрагментов
        document_service = DocumentService()
        has_fragments = document_service.has_approved_fragments([page_id])

        if has_fragments:
            logger.info("[_analyze_page_template_if_needed] -> Page %s has approved fragments, skipping template analysis",
                        page_id)
            return None

        logger.info("[_analyze_page_template_if_needed] Page %s has no approved fragments, analyzing template", page_id)

        # Определяем тип шаблона
        template_type = analyze_page_template_type(page_id)

        if not template_type:
            logger.info("[_analyze_page_template_if_needed] -> No template type identified for page %s", page_id)
            return {
                "template_type": None,
                "template_analysis": None,
                "reason": "Template type not identified"
            }

        logger.info("[_analyze_page_template_if_needed] Template type is '%s' for page %s", template_type,
                    page_id)

        template_analysis_items = [{
            "requirement_type": template_type,
            "page_id": page_id
        }]

        # Проводим анализ соответствия шаблону
        template_analysis_results = analyze_with_templates(
            items=template_analysis_items,
            service_code=service_code
        )

        if template_analysis_results:
            analysis_result = template_analysis_results[0]
            logger.info("[_analyze_page_template_if_needed] -> Template analysis completed for page %s", page_id)

            return {
                "template_type": template_type,
                "template_analysis": analysis_result.get("template_analysis"),
                "legacy_formatting_issues": analysis_result.get("legacy_formatting_issues", []),
                "analysis_timestamp": analysis_result.get("analysis_timestamp"),
                "storage_used": analysis_result.get("storage_used")
            }
        else:
            logger.warning("[_analyze_page_template_if_needed] -> Template analysis failed for page %s", page_id)
            return {
                "template_type": template_type,
                "template_analysis": None,
                "reason": "Template analysis failed"
            }

    except Exception as e:
        logger.error("[_analyze_page_template_if_needed] -> Error analyzing template for page %s: %s", page_id, str(e))
        return {
            "template_type": None,
            "template_analysis": None,
            "error": str(e)
        }


def analyze_with_templates(items: List[dict], prompt_template: Optional[str] = None,
                           service_code: Optional[str] = None):
    """
    Анализирует новые требования и их соответствие шаблонам с передачей шаблона в LLM.
    ИЗМЕНЕНО: Добавляет заголовки к содержимому страниц.
    """
    logger.info("[analyze_with_templates] <- items count: %d, service_code: %s", len(items), service_code)

    if not service_code:
        page_ids = [item["page_id"] for item in items]
        service_code = resolve_service_code_from_pages_or_user(page_ids)
        logger.info("[analyze_with_templates] Resolved service_code: %s", service_code)

    # ДОБАВЛЯЕМ ИМПОРТЫ
    from app.page_cache import get_page_data_cached
    from app.services.template_type_analysis import get_template_name_by_type

    results = []
    template_chain = build_template_analysis_chain(prompt_template)

    for item in items:
        requirement_type = item["requirement_type"]
        page_id = item["page_id"]

        logger.info("[analyze_with_templates] Processing page_id: %s, type: %s", page_id, requirement_type)

        # ИЗМЕНЕНО: Получаем все данные страницы через кеш
        page_data = get_page_data_cached(page_id)

        if not page_data:
            logger.warning("[analyze_with_templates] Could not load page data for %s", page_id)
            results.append({
                "page_id": page_id,
                "requirement_type": requirement_type,
                "template_analysis": {
                    "error": "Не удалось загрузить данные страницы",
                    "page_data_available": False
                },
                "legacy_formatting_issues": []
            })
            continue

        # Формируем содержимое с заголовком
        raw_content = page_data['full_content']
        title = page_data['title']
        requirement_type_name = get_template_name_by_type(requirement_type) if requirement_type else "Неизвестный тип"

        # Добавляем заголовок к содержимому
        header = f"---\npage_id: {page_id}\ntitle: {title}\ntype: {requirement_type_name}\n---\n"
        content = header + raw_content

        template_txt = get_template_by_type(requirement_type)

        if not raw_content or not template_txt:
            logger.warning("[analyze_with_templates] Missing content or template for page %s", page_id)
            results.append({
                "page_id": page_id,
                "requirement_type": requirement_type,
                "template_analysis": {
                    "error": "Отсутствует содержимое страницы или шаблон",
                    "template_available": bool(template_txt),
                    "content_available": bool(raw_content)
                },
                "legacy_formatting_issues": []
            })
            continue

        template_content = template_txt
        context = ""

        # Быстрая структурная проверка (legacy поддержка)
        legacy_formatting_issues = perform_legacy_structure_check(template_txt, raw_content)

        try:
            logger.debug(
                "[analyze_with_templates] Sending to LLM: template=%d chars, content=%d chars, context=%d chars",
                len(template_content), len(content), len(context))

            # ИЗМЕНЕНО: Отправляем содержимое с заголовком
            llm_result = template_chain.run({
                "requirement": content,  # Теперь включает заголовок
                "template": template_content,
                "context": context
            })

            # Остальной код остается без изменений...
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
    required_sections = ["template_compliance", "recommendations", "summary"]
    missing_sections = [section for section in required_sections if section not in parsed_result]

    if missing_sections:
        logger.warning("[_parse_llm_template_response] Missing sections in LLM response: %s", missing_sections)
        for section in missing_sections:
            parsed_result[section] = {"error": f"Section {section} missing from LLM response"}

    return parsed_result
