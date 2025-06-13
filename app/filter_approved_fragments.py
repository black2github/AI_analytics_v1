# app/filter_approved_fragments.py

import logging
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup, Tag, NavigableString
import re
import sys
import io
from app.history_cleaner import remove_history_sections

logger = logging.getLogger(__name__)  # Лучше использовать __name__ для именованных логгеров

def is_strictly_black_color(color_value: str) -> bool:
    """Проверяет черный цвет и часть цветов из верхней строки редактора Confluence"""
    color_value = color_value.strip().lower()
    black_colors = {
        'black', '#000', '#000000',
        'rgb(0,0,0)', 'rgb(0, 0, 0)',
        'rgba(0,0,0,1)', 'rgba(0, 0, 0, 1)',
        'rgb(51,51,0)', 'rgb(51, 51, 0)',
        'rgb(0,51,0)', 'rgb(0, 51, 0)',
        'rgb(0,51,102)', 'rgb(0, 51, 102)',
        'rgb(51,51,51)', 'rgb(51, 51, 51)',
        'rgb(23,43,77)', 'rgb(23, 43, 77)'  # Этот цвет тоже может быть черным
    }
    return color_value in black_colors

def has_colored_style(element: Tag) -> bool:
    """Проверяет, имеет ли элемент цветной стиль"""
    if not isinstance(element, Tag):
        return False

    style = element.get("style", "").lower()
    if not style or "color" not in style:
        return False

    color_match = re.search(r'color\s*:\s*([^;]+)', style)
    if not color_match:
        return False

    color_value = color_match.group(1).strip()
    return not is_strictly_black_color(color_value)

def filter_approved_fragments(html: str) -> str:
    """
    Извлекает подтвержденные фрагменты с гибридной разметкой (Markdown + HTML)
    """
    logger.info("[filter_approved_fragments] <- {%s}", html)

    if not html or not html.strip():
        return ""

    # ДОБАВЛЯЕМ ОЧИСТКУ ИСТОРИИ ИЗМЕНЕНИЙ В НАЧАЛЕ
    html = remove_history_sections(html)

    soup = BeautifulSoup(html, "html.parser")

    # Извлекаем содержимое expand блоков
    for expand in soup.find_all("ac:structured-macro", {"ac:name": "expand"}):
        rich_text_body = expand.find("ac:rich-text-body")
        if rich_text_body:
            expand.replace_with(rich_text_body)

    def is_in_colored_ancestor_chain(element: Tag) -> bool:
        """Проверяет, есть ли цветные предки у элемента"""
        current = element.parent
        while current and isinstance(current, Tag):
            if current.name == "ac:rich-text-body":
                break
            if has_colored_style(current):
                return True
            current = current.parent
        return False

    def get_text_block_color_status(element) -> Optional[bool]:
        """Определяет статус текстового блока"""
        if isinstance(element, NavigableString):
            text = str(element).strip()
            if text:
                return False  # Текстовый узел без стиля = подтвержденный
            return None  # Пустой текст

        if isinstance(element, Tag):
            if element.name in ["br", "ac:structured-macro"]:
                return None

            text_content = element.get_text(strip=True)
            if not text_content:
                return None  # Нет текста

            if has_colored_style(element):
                return True  # Цветной блок
            else:
                return False  # Подтвержденный блок

        return None

    def analyze_link_neighbors(link_element: Tag) -> bool:
        """Анализирует соседние блоки ссылки"""
        if not link_element.parent:
            return True

        parent = link_element.parent
        all_children = list(parent.children)

        try:
            link_index = all_children.index(link_element)
        except ValueError:
            return True

        # Ищем ближайший текстовый блок СЛЕВА
        left_block_status = None
        for i in range(link_index - 1, -1, -1):
            status = get_text_block_color_status(all_children[i])
            if status is not None:
                left_block_status = status
                break

        # Ищем ближайший текстовый блок СПРАВА
        right_block_status = None
        for i in range(link_index + 1, len(all_children)):
            status = get_text_block_color_status(all_children[i])
            if status is not None:
                right_block_status = status
                break

        # Применяем правила
        if left_block_status is None and right_block_status is None:
            return True
        elif left_block_status is None:
            left_block_status = right_block_status
        elif right_block_status is None:
            right_block_status = left_block_status

        # Если ОБА соседних блока цветные - ссылка исключается
        if left_block_status and right_block_status:
            return False
        else:
            return True

    def extract_black_elements_from_colored_container(element) -> str:
        """Ищет только явно черные элементы в цветном контейнере"""
        if isinstance(element, NavigableString):
            return ""

        if not isinstance(element, Tag):
            return ""

        # Если элемент имеет явно черный стиль - извлекаем его содержимое
        style = element.get("style", "").lower()
        if "color" in style:
            color_match = re.search(r'color\s*:\s*([^;]+)', style)
            if color_match:
                color_value = color_match.group(1).strip()
                if is_strictly_black_color(color_value):
                    return extract_approved_text(element)

        # Рекурсивный поиск черных элементов
        approved_parts = []

        for child in element.children:
            if isinstance(child, NavigableString):
                continue
            elif isinstance(child, Tag):
                # ===== ПРОВЕРЯЕМ ЧЕРНЫЕ ЦВЕТА НАПРЯМУЮ =====
                child_style = child.get("style", "").lower()
                child_is_black = False

                if "color" in child_style:
                    color_match = re.search(r'color\s*:\s*([^;]+)', child_style)
                    if color_match:
                        color_value = color_match.group(1).strip()
                        child_is_black = is_strictly_black_color(color_value)

                if child_is_black:
                    # Черный дочерний элемент - извлекаем напрямую
                    child_text = child.get_text(strip=True)
                    if child_text:
                        approved_parts.append(child_text)
                elif has_colored_style(child):
                    # Цветной дочерний элемент - рекурсивно ищем в нем черные части
                    child_text = extract_black_elements_from_colored_container(child)
                    if child_text:
                        approved_parts.append(child_text)
                else:
                    # Элемент без цвета - обрабатываем как обычно
                    child_text = extract_approved_text(child)
                    if child_text:
                        approved_parts.append(child_text)

        # ИСПРАВЛЕНО: Соединяем БЕЗ лишних пробелов
        return "".join(approved_parts)

    def extract_approved_text(element) -> str:
        """Извлекает только подтвержденный текст из элемента"""
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

        if element.name == "ac:parameter" and element.parent and \
                element.parent.name == "ac:structured-macro" and \
                element.parent.get("ac:name") == "jira":
            return ""

        # Время - только если элемент подтвержден
        if element.name == "time" and element.get("datetime"):
            if not has_colored_style(element) and not is_in_colored_ancestor_chain(element):
                return element["datetime"]
            return ""

        # Обработка ссылок
        if element.name in ["a", "ac:link"]:
            if is_in_colored_ancestor_chain(element):
                return ""

            if not analyze_link_neighbors(element):
                return ""

            ri_page = element.find("ri:page")
            if ri_page and ri_page.get("ri:content-title"):
                return f'[{ri_page["ri:content-title"]}]'
            elif element.get_text(strip=True):
                return f'[{element.get_text(strip=True)}]'
            else:
                return ""

        # Если элемент сам имеет цветной стиль - ищем только черные дочерние элементы
        if has_colored_style(element):
            return extract_black_elements_from_colored_container(element)

        # Элемент не имеет цветного стиля, но проверяем предков
        if is_in_colored_ancestor_chain(element):
            return ""

        # ===== ИСПРАВЛЕНИЕ: БОЛЕЕ ТОЧНАЯ ОБРАБОТКА БЕЗ ЛИШНИХ ПРОБЕЛОВ =====
        result_parts = []

        for child in element.children:
            if isinstance(child, NavigableString):
                # Текстовый узел - сохраняем как есть (включая пробелы)
                text = str(child)
                if text:  # Не делаем strip() здесь!
                    result_parts.append(text)
            elif isinstance(child, Tag):
                # Для тегов извлекаем содержимое рекурсивно
                child_text = extract_approved_text(child)
                if child_text:  # Здесь тоже не делаем strip()!
                    result_parts.append(child_text)

        # ИСПРАВЛЕНО: Соединяем БЕЗ дополнительных пробелов
        result = "".join(result_parts)  # Это правильно

        # Убираем только множественные пробелы, но сохраняем исходную структуру
        result = re.sub(r'[ \t]+', ' ', result)

        return result.strip()  # strip() только в самом конце

    def process_table_cell(cell, is_nested=False):
        """Обрабатывает содержимое ячейки таблицы"""
        nested_table = cell.find("table")

        if nested_table:
            # Ячейка содержит вложенную таблицу
            # Сначала извлекаем текст ДО таблицы
            text_before = ""
            for child in cell.children:
                if child == nested_table:
                    break
                if isinstance(child, NavigableString):
                    text_before += str(child)
                elif isinstance(child, Tag) and child.name != "table":
                    text_before += extract_approved_text(child)

            # Обрабатываем вложенную таблицу
            nested_table_html = process_nested_table_to_html(nested_table)

            # Извлекаем текст ПОСЛЕ таблицы
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
                        text_after += extract_approved_text(child)

            # Объединяем результат
            result_parts = []
            if text_before.strip():
                result_parts.append(text_before.strip())
            if nested_table_html:
                result_parts.append(f"**Таблица:** {nested_table_html}")
            if text_after.strip():
                result_parts.append(text_after.strip())

            return " ".join(result_parts)
        else:
            # Обработка списков в ячейках таблицы
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
                            # ===== ИСПРАВЛЕНИЕ: ОСОБАЯ ОБРАБОТКА СПИСКОВ В ЯЧЕЙКАХ =====
                            list_content = process_list_in_cell(child, 0)  # Новая функция!
                            if list_content:
                                cell_parts.append(list_content)
                        else:
                            # Обычный элемент
                            text = extract_approved_text(child)
                            if text.strip():
                                cell_parts.append(text.strip())

                return "\n".join(cell_parts)
            else:
                # Обычная ячейка без списков
                return extract_approved_text(cell)

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

                # ИСПРАВЛЕНИЕ 3: Специальная обработка ссылок во вложенных таблицах
                cell_content = extract_approved_text_for_nested_table(cell)
                row_parts.append(f"<{tag_name}{attrs_str}>{cell_content}</{tag_name}>")

            row_parts.append("</tr>")
            html_parts.append("".join(row_parts))

        html_parts.append("</table>")
        return "".join(html_parts)

    def extract_approved_text_for_nested_table(element) -> str:
        """Специальная функция для извлечения текста из вложенных таблиц"""
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

        # Время - только если элемент подтвержден
        if element.name == "time" and element.get("datetime"):
            if not has_colored_style(element) and not is_in_colored_ancestor_chain(element):
                return element["datetime"]
            return ""

        # ИСПРАВЛЕНИЕ 4: Упрощенная обработка ссылок для вложенных таблиц
        if element.name in ["a", "ac:link"]:
            # НОВАЯ ЛОГИКА: Проверяем сам элемент ссылки и его прямого родителя
            if has_colored_style(element):
                return ""  # Цветная ссылка - исключаем

            # ИСПРАВЛЕНИЕ: Проверяем родительский элемент только на один уровень вверх
            # и только если он не является ячейкой таблицы
            parent = element.parent
            if parent and isinstance(parent, Tag) and parent.name not in ["td", "th"]:
                if has_colored_style(parent):
                    return ""  # Ссылка в цветном контейнере - исключаем

            # Для подтвержденных ссылок
            ri_page = element.find("ri:page")
            if ri_page and ri_page.get("ri:content-title"):
                return f'[{ri_page["ri:content-title"]}]'
            elif element.get_text(strip=True):
                return f'[{element.get_text(strip=True)}]'
            else:
                return ""

        # Если элемент сам цветной - ищем черные дочерние элементы
        if has_colored_style(element):
            approved_parts = []
            for child in element.children:
                if isinstance(child, Tag):
                    # ИСПРАВЛЕНИЕ: Рекурсивно вызываем функцию для дочерних элементов
                    child_text = extract_approved_text_for_nested_table(child)
                    if child_text:
                        approved_parts.append(child_text)
                elif isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        approved_parts.append(text)
            # ✅ ИСПРАВЛЕНО: Убираем лишние пробелы
            return "".join(approved_parts)  # Было " ".join(approved_parts)

        # ИСПРАВЛЕНИЕ: Убираем проверку цветных предков для вложенных таблиц
        # Это позволит обрабатывать черные ссылки в цветных ячейках

        # ИСПРАВЛЕНИЕ: Рекурсивно обрабатываем дочерние элементы БЕЗ ЛИШНИХ ПРОБЕЛОВ
        result_parts = []
        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text:
                    result_parts.append(text)
            elif isinstance(child, Tag):
                child_text = extract_approved_text_for_nested_table(child)
                if child_text:
                    result_parts.append(child_text)

        # ✅ ИСПРАВЛЕНО: Соединяем БЕЗ лишних пробелов
        result = "".join(result_parts)  # Было " ".join(child_texts)

        # Нормализуем пробелы
        result = re.sub(r'[ \t]+', ' ', result)

        return result.strip()

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
            row_has_content = False  # Переносим проверку выше

            is_header_row = all(cell.name == "th" for cell in cells)

            for cell in cells:
                # Получаем содержимое ячейки
                cell_content = process_table_cell(cell)

                # Проверяем, есть ли реальное содержимое в ячейке
                if cell_content and cell_content.strip():
                    row_has_content = True

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

            # Добавляем строку только если в ней есть реальное содержимое
            if row_has_content:
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
                        text = extract_approved_text(child)
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
                header_text = extract_approved_text(element)
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
                para_text = extract_approved_text(element)
                if para_text.strip():
                    result_parts.append(para_text.strip())

            elif element.name in ["div", "span"]:
                # Обработка div/span элементов
                div_text = extract_approved_text(element)
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

    def process_list_in_cell(list_element: Tag, indent_level: int = 0) -> str:
        """Обрабатывает список в ячейке таблицы с особой логикой для цветных элементов"""
        list_items = []
        indent = "    " * indent_level

        if list_element.name == "ul":
            markers = ["-", "*", "+"]
            marker = markers[indent_level % len(markers)]
        else:
            marker = None

        item_counter = 1

        for li in list_element.find_all("li", recursive=False):
            # ===== СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ ЯЧЕЕК ТАБЛИЦЫ =====
            # Извлекаем ВСЕ подтвержденное содержимое элемента li
            item_text = extract_approved_text(li)

            if item_text.strip():
                if list_element.name == "ul":
                    list_items.append(f"{indent}{marker} {item_text.strip()}")
                else:
                    list_items.append(f"{indent}{item_counter}. {item_text.strip()}")
                    item_counter += 1

            # Обрабатываем вложенные списки
            nested_lists = li.find_all(["ul", "ol"], recursive=False)
            for nested_list in nested_lists:
                nested_content = process_list_in_cell(nested_list, indent_level + 1)
                if nested_content:
                    list_items.append(nested_content)

        return "\n".join(list_items)

    # Основная обработка
    approved_fragments = process_elements_sequentially(soup)
    # В конце функции filter_approved_fragments, перед return:
    result = "\n\n".join(approved_fragments)
    result = re.sub(r'\n\s*\n+', '\n\n', result)
    # ===== ИСПРАВЛЕНИЕ: УБИРАЕМ ЛИШНИЕ ПРОБЕЛЫ =====
    result = re.sub(r'[ \t]+', ' ', result)  # Заменяем множественные пробелы на один
    result = re.sub(r' +\.', '.', result)  # Убираем пробелы перед точками
    result = re.sub(r' +,', ',', result)  # Убираем пробелы перед запятыми

    logger.info("[filter_approved_fragments] -> {%s}", result[:500]+"...")

    return result.strip()


# Тестирование
if __name__ == "__main__":

    # Настройка кодировки для Windows консоли
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


    def test_pointwise_fixes():
        """Тест точечных исправлений"""

        html_content = ''' '''

        result = filter_approved_fragments(html_content)

        print("=" * 80)
        print(f"Результат:")
        print(result)
        print("=" * 80)


    # Запускаем тест
    test_pointwise_fixes()