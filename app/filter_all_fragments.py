# app/filter_all_fragments.py

import logging
from typing import List
from bs4 import BeautifulSoup, Tag, NavigableString
import re
import sys
import io
from app.history_cleaner import remove_history_sections

logger = logging.getLogger(__name__)


def _clean_bracket_content(content: str) -> str:
    """Умная очистка содержимого треугольных скобок"""
    if not content:
        return ''

    # 1. Убираем лишние пробелы в начале и конце
    content = content.strip()

    # 2. Нормализуем множественные пробелы
    content = re.sub(r'\s+', ' ', content)

    # 3. ИСПРАВЛЕНИЕ: Правильная обработка кавычек
    # Убираем пробел ПОСЛЕ открывающей кавычки: " текст -> "текст
    content = re.sub(r'"\s+', '"', content)
    # Убираем пробел ПЕРЕД закрывающей кавычкой: текст " -> текст"
    content = re.sub(r'\s+"', '"', content)
    # НО добавляем пробел ПЕРЕД открывающей кавычкой, если его нет
    content = re.sub(r'(\w)"', r'\1 "', content)  # слово"текст -> слово "текст

    # 4. Обработка квадратных скобок аналогично
    content = re.sub(r'\[\s+', '[', content)  # [ текст -> [текст
    content = re.sub(r'\s+\]', ']', content)  # текст ] -> текст]

    return content

def filter_all_fragments(html: str) -> str:
    """
    Извлекает все фрагменты из HTML возвращая их с гибридной разметкой (Markdown + HTML)
    без учета цвета элементов
    """
    logger.info("[filter_all_fragments] <- {%s}", html)
    if not html or not html.strip():
        return ""

    html = remove_history_sections(html)
    soup = BeautifulSoup(html, "html.parser")

    # Извлекаем содержимое expand блоков
    for expand in soup.find_all("ac:structured-macro", {"ac:name": "expand"}):
        rich_text_body = expand.find("ac:rich-text-body")
        if rich_text_body:
            expand.replace_with(rich_text_body)

    def extract_all_text(element) -> str:
        """Извлекает весь текст из элемента независимо от цвета"""
        if isinstance(element, NavigableString):
            return str(element)

        if not isinstance(element, Tag):
            return ""

        # Игнорируем зачеркнутый текст всегда
        if element.name == "s":
            return ""

        # Игнорируем Jira макросы всегда и ВСЕ их параметры
        if element.name == "ac:structured-macro" and element.get("ac:name") == "jira":
            return ""

        if element.name == "ac:parameter" and element.parent and \
                element.parent.name == "ac:structured-macro" and \
                element.parent.get("ac:name") == "jira":
            return ""

        # Время
        if element.name == "time" and element.get("datetime"):
            return element["datetime"]

        # Обработка ссылок
        if element.name in ["a", "ac:link"]:
            ri_page = element.find("ri:page")
            if ri_page and ri_page.get("ri:content-title"):
                return f'[{ri_page["ri:content-title"]}]'
            elif element.get_text(strip=True):
                return f'[{element.get_text(strip=True)}]'
            else:
                return ""

        # ИСПРАВЛЕНИЕ: Более умная обработка дочерних элементов
        result_parts = []
        prev_was_tag = False

        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text:
                    result_parts.append(text)
                    prev_was_tag = False
            elif isinstance(child, Tag):
                child_text = extract_all_text(child)
                if child_text:
                    # КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: добавляем пробел между тегами, если нужно
                    if prev_was_tag and result_parts and not result_parts[-1].endswith(
                            ' ') and not child_text.startswith(' '):
                        result_parts.append(' ')
                    result_parts.append(child_text)
                    prev_was_tag = True

        # Соединяем БЕЗ дополнительных пробелов
        result = "".join(result_parts)

        # Нормализация
        result = re.sub(r'[ \t]{2,}', ' ', result)
        result = re.sub(r'<\s*([^<>]*?)\s*>', lambda m: f'<{_clean_bracket_content(m.group(1))}>', result)
        result = re.sub(r'<\s*>', '<>', result)

        # ДОБАВЛЯЕМ: замена переносов строк на пробелы внутри одного элемента
        result = re.sub(r'\n+', ' ', result)
        result = re.sub(r' {2,}', ' ', result)

        result = re.sub(r'\]\s+\.', '].', result)
        result = re.sub(r'>\s+\.', '>.', result)

        return result.strip()

    def process_table_cell(cell, is_nested=False):
        """Обрабатывает содержимое ячейки таблицы"""
        nested_table = cell.find("table")

        if nested_table:
            text_before = ""
            for child in cell.children:
                if child == nested_table:
                    break
                if isinstance(child, NavigableString):
                    text_before += str(child)
                elif isinstance(child, Tag) and child.name != "table":
                    text_before += extract_all_text(child)

            nested_table_html = process_nested_table_to_html(nested_table)

            text_after = ""
            found_table = False
            for child in cell.children:
                if child == nested_table:
                    found_table = True
                    continue
                if found_table:
                    if isinstance(child, NavigableString):
                        text_after += str(child)
                    elif isinstance(child, Tag) and child.name != "table":
                        text_after += extract_all_text(child)

            result_parts = []
            if text_before.strip():
                result_parts.append(text_before.strip())
            if nested_table_html:
                result_parts.append(f"**Таблица:** {nested_table_html}")
            if text_after.strip():
                result_parts.append(text_after.strip())

            return "".join(result_parts)
        else:
            lists = cell.find_all(["ul", "ol"], recursive=False)

            if lists:
                cell_parts = []

                for child in cell.children:
                    if isinstance(child, NavigableString):
                        text = str(child).strip()
                        if text:
                            cell_parts.append(text)
                    elif isinstance(child, Tag):
                        if child.name in ["ul", "ol"]:
                            list_content = process_list_in_cell_all(child, 0)
                            if list_content:
                                cell_parts.append(list_content)
                        else:
                            text = extract_all_text(child)
                            if text.strip():
                                cell_parts.append(text.strip())

                return "\n".join(cell_parts)
            else:
                deep_lists = cell.find_all(["ul", "ol"], recursive=True)
                if deep_lists:
                    result_parts = []
                    for child in cell.children:
                        if isinstance(child, NavigableString):
                            text = str(child).strip()
                            if text:
                                result_parts.append(text)
                        elif isinstance(child, Tag):
                            child_text = extract_all_text_for_lists(child)
                            if child_text:
                                result_parts.append(child_text)

                    return "\n".join(result_parts)
                else:
                    return extract_all_text(cell)

    def extract_all_text_for_lists(element) -> str:
        """Специальная функция для извлечения списков из любых контейнеров"""
        if isinstance(element, NavigableString):
            return str(element).strip()

        if not isinstance(element, Tag):
            return ""

        if element.name in ["ul", "ol"]:
            return process_list_in_cell_all(element, 0)

        lists = element.find_all(["ul", "ol"], recursive=False)
        if lists:
            result_parts = []

            for child in element.children:
                if isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        result_parts.append(text)
                elif isinstance(child, Tag):
                    if child.name in ["ul", "ol"]:
                        list_content = process_list_in_cell_all(child, 0)
                        if list_content:
                            result_parts.append(list_content)
                    else:
                        text = extract_all_text(child)
                        if text.strip():
                            result_parts.append(text.strip())

            return "\n".join(result_parts)

        result = extract_all_text(element)
        result = re.sub(r'<\s*([^<>]*?)\s*>', lambda m: f'<{_clean_bracket_content(m.group(1))}>', result)

        return result

    def process_nested_table_to_html(table: Tag) -> str:
        """Преобразует вложенную таблицу в HTML"""
        rows = table.find_all("tr", recursive=False)
        if not rows:
            tbody = table.find("tbody")
            thead = table.find("thead")
            if tbody:
                rows.extend(tbody.find_all("tr", recursive=False))
            if thead:
                rows.extend(thead.find_all("tr", recursive=False))

        if not rows:
            return ""

        html_parts = ["<table>"]

        for row in rows:
            cells = row.find_all(["td", "th"], recursive=False)

            row_parts = ["<tr>"]
            for cell in cells:
                tag_name = "th" if cell.name == "th" else "td"

                attrs = []
                if cell.get("rowspan") and int(cell.get("rowspan", 1)) > 1:
                    attrs.append(f'rowspan="{cell["rowspan"]}"')
                if cell.get("colspan") and int(cell.get("colspan", 1)) > 1:
                    attrs.append(f'colspan="{cell["colspan"]}"')

                attrs_str = " " + " ".join(attrs) if attrs else ""

                cell_content = extract_all_text_for_nested_table(cell)
                row_parts.append(f"<{tag_name}{attrs_str}>{cell_content}</{tag_name}>")

            row_parts.append("</tr>")
            html_parts.append("".join(row_parts))

        html_parts.append("</table>")
        return "".join(html_parts)

    def extract_all_text_for_nested_table(element) -> str:
        """Извлекает весь текст из вложенных таблиц независимо от цвета"""
        if isinstance(element, NavigableString):
            return str(element).strip()

        if not isinstance(element, Tag):
            return ""

        if element.name == "s":
            return ""

        if element.name == "ac:structured-macro" and element.get("ac:name") == "jira":
            return ""

        if element.name == "time" and element.get("datetime"):
            return element["datetime"]

        if element.name in ["a", "ac:link"]:
            ri_page = element.find("ri:page")
            if ri_page and ri_page.get("ri:content-title"):
                return f'[{ri_page["ri:content-title"]}]'
            elif element.get_text(strip=True):
                return f'[{element.get_text(strip=True)}]'
            else:
                return ""

        if element.name in ["ul", "ol"]:
            return process_list_in_nested_table_all(element, 0)

        lists = element.find_all(["ul", "ol"], recursive=False)
        if lists:
            result_parts = []

            for child in element.children:
                if isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        result_parts.append(text)
                elif isinstance(child, Tag):
                    if child.name in ["ul", "ol"]:
                        list_content = process_list_in_nested_table_all(child, 0)
                        if list_content:
                            result_parts.append(list_content)
                    else:
                        child_text = extract_all_text_for_nested_table(child)
                        if child_text:
                            result_parts.append(child_text)

            return "\n".join(result_parts)

        result_parts = []
        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text:
                    result_parts.append(text)
            elif isinstance(child, Tag):
                child_text = extract_all_text_for_nested_table(child)
                if child_text:
                    result_parts.append(child_text)

        result = "".join(result_parts)
        result = re.sub(r'[ \t]+', ' ', result)

        # ДОБАВИТЬ: Применяем очистку треугольных скобок
        result = re.sub(r'<\s*([^<>]*?)\s*>', lambda m: f'<{_clean_bracket_content(m.group(1))}>', result)
        result = re.sub(r'<\s*>', '<>', result)

        if not re.search(r'[-*+]\s|\d+\.\s', result):
            result = re.sub(r'\s+', ' ', result)

        return result.strip()

    def process_list_in_nested_table_all(list_element: Tag, indent_level: int = 0) -> str:
        """Обрабатывает список во вложенной таблице для filter_all_fragments"""
        list_items = []
        indent = "    " * indent_level

        if list_element.name == "ul":
            markers = ["-", "*", "+"]
            marker = markers[indent_level % len(markers)]
        else:
            marker = None

        item_counter = 1

        for li in list_element.find_all("li", recursive=False):
            item_content_parts = []

            for child in li.children:
                if isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        item_content_parts.append(text)
                elif isinstance(child, Tag):
                    if child.name in ["ul", "ol"]:
                        continue
                    else:
                        text = child.get_text(strip=True)
                        if text:
                            item_content_parts.append(text)

            item_text = " ".join(item_content_parts)

            if item_text.strip():
                if list_element.name == "ul":
                    list_items.append(f"{indent}{marker} {item_text.strip()}")
                else:
                    list_items.append(f"{indent}{item_counter}. {item_text.strip()}")
                    item_counter += 1

            nested_lists = li.find_all(["ul", "ol"], recursive=False)
            for nested_list in nested_lists:
                nested_content = process_list_in_nested_table_all(nested_list, indent_level + 1)
                if nested_content:
                    list_items.append(nested_content)

        result = "\n".join(list_items)

        # ДОБАВИТЬ: Очистка треугольных скобок в результате
        result = re.sub(r'<\s*([^<>]*?)\s*>', lambda m: f'<{_clean_bracket_content(m.group(1))}>', result)

        return result


    def process_table(table: Tag) -> str:
        """Обрабатывает таблицу с гибридной разметкой"""
        rows = table.find_all("tr", recursive=False)
        if not rows:
            tbody = table.find("tbody")
            thead = table.find("thead")
            if tbody:
                rows.extend(tbody.find_all("tr", recursive=False))
            if thead:
                rows.extend(thead.find_all("tr", recursive=False))

        table_lines = []
        has_headers = False

        for i, row in enumerate(rows):
            cells = row.find_all(["td", "th"], recursive=False)
            row_data = []

            is_header_row = all(cell.name == "th" for cell in cells)

            for cell in cells:
                cell_content = process_table_cell(cell)

                html_attrs = []
                if cell.get("rowspan") and int(cell.get("rowspan", 1)) > 1:
                    html_attrs.append(f'rowspan="{cell["rowspan"]}"')
                if cell.get("colspan") and int(cell.get("colspan", 1)) > 1:
                    html_attrs.append(f'colspan="{cell["colspan"]}"')

                if html_attrs:
                    attrs_str = " ".join(html_attrs)
                    cell_text = f'<td {attrs_str}>{cell_content}</td>' if cell_content else f'<td {attrs_str}></td>'
                else:
                    cell_text = cell_content if cell_content else ""

                row_data.append(cell_text)

            if is_header_row and not has_headers:
                table_lines.append("| " + " | ".join(row_data) + " |")
                table_lines.append("|" + "|".join([" --- " for _ in row_data]) + "|")
                has_headers = True
            else:
                table_lines.append("| " + " | ".join(row_data) + " |")

        return "\n".join(table_lines) if table_lines else ""

    def process_list(list_element: Tag, indent_level: int = 0) -> str:
        """Обрабатывает список с поддержкой вложенности"""
        list_items = []
        indent = "    " * indent_level

        if list_element.name == "ul":
            markers = ["-", "*", "+"]
            marker = markers[indent_level % len(markers)]
        else:
            marker = None

        item_counter = 1

        for li in list_element.find_all("li", recursive=False):
            item_content_parts = []

            for child in li.children:
                if isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        item_content_parts.append(text)
                elif isinstance(child, Tag):
                    if child.name in ["ul", "ol"]:
                        continue
                    else:
                        text = extract_all_text(child)
                        if text.strip():
                            item_content_parts.append(text.strip())

            item_text = " ".join(item_content_parts)

            if item_text.strip():
                if list_element.name == "ul":
                    list_items.append(f"{indent}{marker} {item_text.strip()}")
                else:
                    list_items.append(f"{indent}{item_counter}. {item_text.strip()}")
                    item_counter += 1

            nested_lists = li.find_all(["ul", "ol"], recursive=False)
            for nested_list in nested_lists:
                nested_content = process_list(nested_list, indent_level + 1)
                if nested_content:
                    list_items.append(nested_content)

        result = "\n".join(list_items)

        # Очистка треугольных скобок в результате
        result = re.sub(r'<\s*([^<>]*?)\s*>', lambda m: f'<{_clean_bracket_content(m.group(1))}>', result)

        return result


    def process_list_in_cell_all(list_element: Tag, indent_level: int = 0) -> str:
        """Обрабатывает список в ячейке таблицы для filter_all_fragments (ВСЕ фрагменты)"""
        list_items = []
        indent = "    " * indent_level

        if list_element.name == "ul":
            markers = ["-", "*", "+"]
            marker = markers[indent_level % len(markers)]
        else:
            marker = None

        item_counter = 1

        for li in list_element.find_all("li", recursive=False):
            item_content_parts = []

            for child in li.children:
                if isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        item_content_parts.append(text)
                elif isinstance(child, Tag):
                    if child.name in ["ul", "ol"]:
                        continue
                    else:
                        text = extract_all_text(child)
                        if text.strip():
                            item_content_parts.append(text.strip())

            item_text = " ".join(item_content_parts)

            if item_text.strip():
                if list_element.name == "ul":
                    list_items.append(f"{indent}{marker} {item_text.strip()}")
                else:
                    list_items.append(f"{indent}{item_counter}. {item_text.strip()}")
                    item_counter += 1

            nested_lists = li.find_all(["ul", "ol"], recursive=False)
            for nested_list in nested_lists:
                nested_content = process_list_in_cell_all(nested_list, indent_level + 1)
                if nested_content:
                    list_items.append(nested_content)

        result = "\n".join(list_items)

        # ✅ ДОБАВИТЬ: Очистка треугольных скобок в результате
        result = re.sub(r'<\s*([^<>]*?)\s*>', lambda m: f'<{_clean_bracket_content(m.group(1))}>', result)

        return result

    def process_elements_sequentially(container) -> List[str]:
        """Обрабатывает элементы в том порядке, как они идут в HTML"""
        result_parts = []

        for element in container.find_all(True, recursive=False):
            if element.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                header_text = extract_all_text(element)
                if header_text.strip():
                    level_prefix = "#" * int(element.name[1])
                    result_parts.append(f"{level_prefix} {header_text.strip()}")

            elif element.name == "table":
                table_content = process_table(element)
                if table_content.strip():
                    result_parts.append(f"**Таблица:**\n{table_content}")

            elif element.name in ["ul", "ol"]:
                list_content = process_list(element, 0)
                if list_content:
                    result_parts.append(list_content)

            elif element.name == "p":
                para_text = extract_all_text(element)
                if para_text.strip():
                    result_parts.append(para_text.strip())

            elif element.name in ["div", "span"]:
                # ИСПРАВЛЕНИЕ: Сначала проверяем, есть ли заголовки внутри div
                inner_headers = element.find_all(["h1", "h2", "h3", "h4", "h5", "h6"], recursive=False)
                if inner_headers:
                    # Если есть заголовки - обрабатываем рекурсивно
                    nested_parts = process_elements_sequentially(element)
                    result_parts.extend(nested_parts)
                else:
                    # Обычная обработка div/span элементов
                    div_text = extract_all_text(element)
                    if div_text.strip():
                        result_parts.append(div_text.strip())

            elif element.name == "ac:rich-text-body":
                nested_parts = process_elements_sequentially(element)
                result_parts.extend(nested_parts)

            elif element.name == "ac:layout":
                nested_parts = process_elements_sequentially(element)
                result_parts.extend(nested_parts)

            elif element.name == "ac:layout-section":
                nested_parts = process_elements_sequentially(element)
                result_parts.extend(nested_parts)

            elif element.name == "ac:layout-cell":
                nested_parts = process_elements_sequentially(element)
                result_parts.extend(nested_parts)

        return result_parts

    # Основная обработка
    all_fragments = process_elements_sequentially(soup)
    result = "\n\n".join(all_fragments)
    result = re.sub(r'\n\s*\n+', '\n\n', result)

    # Финальная очистка пробелов перед точками
    result = re.sub(r'\]\s+\.', '].', result)
    result = re.sub(r'>\s+\.', '>.', result)

    logger.info("[filter_all_fragments] -> {%s}", result[:500] + "...")
    # В конце функции filter_all_fragments, перед return:
    print(f"DEBUG all result: '{result}'")
    return result.strip()