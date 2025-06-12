# app/filter_all_fragments.py

import logging
from typing import List
from bs4 import BeautifulSoup, Tag, NavigableString
import re
import sys
import io

logger = logging.getLogger(__name__)  # Лучше использовать __name__ для именованных логгеров

def filter_all_fragments(html: str) -> str:
    """
    Извлекает все фрагменты из HTML возвращая их с гибридной разметкой (Markdown + HTML)
    без учета цвета элементов
    """
    logger.info("[filter_all_fragments] <- {%s}", html)
    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Извлекаем содержимое expand блоков
    for expand in soup.find_all("ac:structured-macro", {"ac:name": "expand"}):
        rich_text_body = expand.find("ac:rich-text-body")
        if rich_text_body:
            expand.replace_with(rich_text_body)

    def extract_all_text(element) -> str:
        """Извлекает весь текст из элемента независимо от цвета"""
        if isinstance(element, NavigableString):
            return str(element).strip()

        if not isinstance(element, Tag):
            return ""

        # Игнорируем зачеркнутый текст всегда
        if element.name == "s":
            return ""

        # Игнорируем Jira макросы всегда и ВСЕ их параметры
        if element.name == "ac:structured-macro" and element.get("ac:name") == "jira":
            return ""

        # Игнорируем ВСЕ параметры Jira макросов
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

        # Рекурсивно обрабатываем дочерние элементы
        child_texts = []
        for child in element.children:
            child_text = extract_all_text(child)
            if child_text.strip():
                child_texts.append(child_text.strip())

        return " ".join(child_texts)

    def process_table_cell(cell, is_nested=False):
        """Обрабатывает содержимое ячейки таблицы"""
        nested_table = cell.find("table")

        if nested_table:
            # Ячейка содержит вложенную таблицу
            # (существующий код остается без изменений)
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

            return " ".join(result_parts)
        else:
            # ===== ИСПРАВЛЕНИЕ: ОБРАБОТКА СПИСКОВ В ЯЧЕЙКАХ =====
            # Ячейка без вложенной таблицы - проверяем наличие списков
            lists = cell.find_all(["ul", "ol"], recursive=False)

            if lists:
                # В ячейке есть списки - обрабатываем их отдельно
                cell_parts = []

                for child in cell.children:
                    if isinstance(child, NavigableString):
                        text = str(child).strip()
                        if text:
                            cell_parts.append(text)
                    elif isinstance(child, Tag):
                        if child.name in ["ul", "ol"]:
                            # Обрабатываем список с сохранением структуры
                            list_content = process_list(child, 0)
                            if list_content:
                                cell_parts.append(list_content)
                        else:
                            # Обычный элемент
                            text = extract_all_text(child)
                            if text.strip():
                                cell_parts.append(text.strip())

                return "\n".join(cell_parts)
            else:
                # Обычная ячейка без списков
                return extract_all_text(cell)

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

                # Получаем атрибуты rowspan/colspan
                attrs = []
                if cell.get("rowspan") and int(cell.get("rowspan", 1)) > 1:
                    attrs.append(f'rowspan="{cell["rowspan"]}"')
                if cell.get("colspan") and int(cell.get("colspan", 1)) > 1:
                    attrs.append(f'colspan="{cell["colspan"]}"')

                attrs_str = " " + " ".join(attrs) if attrs else ""

                # Извлекаем все содержимое ячейки
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

        # Игнорируем зачеркнутый текст всегда
        if element.name == "s":
            return ""

        # Игнорируем Jira макросы всегда
        if element.name == "ac:structured-macro" and element.get("ac:name") == "jira":
            return ""

        # Время
        if element.name == "time" and element.get("datetime"):
            return element["datetime"]

        # Обработка ссылок для вложенных таблиц
        if element.name in ["a", "ac:link"]:
            ri_page = element.find("ri:page")
            if ri_page and ri_page.get("ri:content-title"):
                return f'[{ri_page["ri:content-title"]}]'
            elif element.get_text(strip=True):
                return f'[{element.get_text(strip=True)}]'
            else:
                return ""

        # Рекурсивно обрабатываем дочерние элементы
        child_texts = []
        for child in element.children:
            child_text = extract_all_text_for_nested_table(child)
            if child_text.strip():
                child_texts.append(child_text.strip())

        return " ".join(child_texts)

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
                # Получаем содержимое ячейки
                cell_content = process_table_cell(cell)

                # Добавляем HTML атрибуты для объединения ячеек
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

            # Добавляем строку с данными
            if is_header_row and not has_headers:
                # Первая строка заголовков
                table_lines.append("| " + " | ".join(row_data) + " |")
                table_lines.append("|" + "|".join([" --- " for _ in row_data]) + "|")
                has_headers = True
            else:
                # Обычная строка данных
                table_lines.append("| " + " | ".join(row_data) + " |")

        return "\n".join(table_lines) if table_lines else ""

    def process_list(list_element: Tag, indent_level: int = 0) -> str:
        """Обрабатывает список с поддержкой вложенности"""
        list_items = []
        indent = "    " * indent_level  # 4 пробела на уровень

        # Определяем символы для разных уровней вложенности
        if list_element.name == "ul":
            # Для ненумерованных списков чередуем символы по уровням
            markers = ["-", "*", "+"]
            marker = markers[indent_level % len(markers)]
        else:
            # Для нумерованных списков всегда цифры с точкой
            marker = None  # будем добавлять номер динамически

        item_counter = 1

        for li in list_element.find_all("li", recursive=False):
            # Извлекаем прямое содержимое элемента li (без вложенных списков)
            item_content_parts = []

            for child in li.children:
                if isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        item_content_parts.append(text)
                elif isinstance(child, Tag):
                    if child.name in ["ul", "ol"]:
                        # Вложенный список обработаем отдельно
                        continue
                    else:
                        # Обычный текстовый элемент
                        text = extract_all_text(child)
                        if text.strip():
                            item_content_parts.append(text.strip())

            # Формируем основной текст пункта
            item_text = " ".join(item_content_parts)

            if item_text.strip():
                # Добавляем маркер и отступ
                if list_element.name == "ul":
                    list_items.append(f"{indent}{marker} {item_text.strip()}")
                else:
                    list_items.append(f"{indent}{item_counter}. {item_text.strip()}")
                    item_counter += 1

            # Обрабатываем вложенные списки
            nested_lists = li.find_all(["ul", "ol"], recursive=False)
            for nested_list in nested_lists:
                nested_content = process_list(nested_list, indent_level + 1)
                if nested_content:
                    list_items.append(nested_content)

        return "\n".join(list_items)


    def process_elements_sequentially(container) -> List[str]:
        """Обрабатывает элементы в том порядке, как они идут в HTML"""
        result_parts = []

        for element in container.find_all(True, recursive=False):
            if element.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                # Заголовки
                header_text = extract_all_text(element)
                if header_text.strip():
                    level_prefix = "#" * int(element.name[1])
                    result_parts.append(f"{level_prefix} {header_text.strip()}")

            elif element.name == "table":
                # Таблицы с маркером
                table_content = process_table(element)
                if table_content.strip():
                    result_parts.append(f"**Таблица:**\n{table_content}")

            elif element.name in ["ul", "ol"]:
                # Списки с поддержкой вложенности
                list_content = process_list(element, 0)  # начинаем с уровня 0
                if list_content:
                    result_parts.append(list_content)

            elif element.name == "p":
                # Параграфы
                para_text = extract_all_text(element)
                if para_text.strip():
                    result_parts.append(para_text.strip())

            elif element.name in ["div", "span"]:
                # Обработка div/span элементов
                div_text = extract_all_text(element)
                if div_text.strip():
                    result_parts.append(div_text.strip())

            elif element.name == "ac:rich-text-body":
                # Рекурсивно обрабатываем содержимое
                nested_parts = process_elements_sequentially(element)
                result_parts.extend(nested_parts)

            # ===== ДОБАВЛЯЕМ ОБРАБОТКУ CONFLUENCE LAYOUT =====
            elif element.name == "ac:layout":
                # Обрабатываем layout контейнер
                nested_parts = process_elements_sequentially(element)
                result_parts.extend(nested_parts)

            elif element.name == "ac:layout-section":
                # Обрабатываем секцию layout
                nested_parts = process_elements_sequentially(element)
                result_parts.extend(nested_parts)

            elif element.name == "ac:layout-cell":
                # Обрабатываем ячейку layout
                nested_parts = process_elements_sequentially(element)
                result_parts.extend(nested_parts)

        return result_parts


    # Основная обработка
    all_fragments = process_elements_sequentially(soup)
    result = "\n\n".join(all_fragments)
    result = re.sub(r'\n\s*\n+', '\n\n', result)
    result = re.sub(r'[ \t]+', ' ', result)

    logger.info("[filter_all_fragments] -> {%s}", result[:500]+"...")

    return result.strip()


# Тестирование
if __name__ == "__main__":

    # Настройка кодировки для Windows консоли
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


    def test_all_fragments():
        """Тест извлечения всех фрагментов"""

        html_content = ''' '''
        result = filter_all_fragments(html_content)

        print("=" * 80)
        print("ТЕСТ ИЗВЛЕЧЕНИЯ ВСЕХ ФРАГМЕНТОВ:")
        print(f"Результат:")
        print(result)
        print("=" * 80)

    # Запускаем тест
    test_all_fragments()