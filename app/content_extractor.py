# app/content_extractor.py

import logging
import re
from typing import List, Optional, Callable, Dict, Any
from bs4 import BeautifulSoup, Tag, NavigableString
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExtractionConfig:
    """Конфигурация для извлечения контента"""
    include_colored: bool = True  # True = все фрагменты, False = только подтвержденные
    normalize_spacing: bool = True
    clean_brackets: bool = True
    format_tables: bool = True
    format_lists: bool = True
    format_headers: bool = True


class ContentExtractor:
    """Единый экстрактор контента с поддержкой разных режимов фильтрации"""

    def __init__(self, config: ExtractionConfig):
        self.config = config

    def extract(self, html: str) -> str:
        """Главная точка входа для извлечения контента"""
        if not html or not html.strip():
            return ""

        # Очистка истории изменений
        from app.history_cleaner import remove_history_sections
        html = remove_history_sections(html)

        soup = BeautifulSoup(html, "html.parser")

        # Извлекаем содержимое expand блоков
        self._process_expand_blocks(soup)

        # Рекурсивная обработка
        result_parts = self._process_container(soup)

        # Финальная сборка
        result = "\n\n".join(result_parts)
        result = self._apply_final_cleanup(result)

        return result.strip()

    def _process_expand_blocks(self, soup: BeautifulSoup):
        """Обработка expand блоков Confluence"""
        for expand in soup.find_all("ac:structured-macro", {"ac:name": "expand"}):
            rich_text_body = expand.find("ac:rich-text-body")
            if rich_text_body:
                expand.replace_with(rich_text_body)

    def _process_container(self, container) -> List[str]:
        """Рекурсивная обработка контейнера"""
        result_parts = []

        for element in container.find_all(True, recursive=False):
            # Проверяем, должен ли элемент быть включен
            if isinstance(element, Tag) and not self._should_include_element(element):
                # В режиме "только подтвержденные" ищем черные элементы
                if not self.config.include_colored:
                    black_content = self._extract_black_elements_from_colored_container(element, "default")
                    if black_content and black_content.strip():
                        result_parts.append(black_content.strip())
                continue

            processed_content = self._process_element(element, context="default")
            if processed_content and processed_content.strip():
                result_parts.append(processed_content.strip())

        return result_parts

    def _process_element(self, element, context: str = "default") -> str:
        """Универсальная рекурсивная обработка элемента"""
        if isinstance(element, NavigableString):
            return self._process_text_node(str(element), context)

        if not isinstance(element, Tag):
            return ""

        # Специальные элементы (игнорируемые)
        if self._is_ignored_element(element):
            return ""

        # Проверяем, должен ли элемент быть включен (цветовая фильтрация)
        if not self._should_include_element(element):
            # В режиме "только подтвержденные" ищем черные дочерние элементы в цветном контейнере
            if not self.config.include_colored:
                return self._extract_black_elements_from_colored_container(element, context)
            return ""

        # Заголовки
        if element.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            return self._process_header(element, context)

        # Таблицы
        if element.name == "table":
            return self._process_table(element, context)

        # Списки
        if element.name in ["ul", "ol"]:
            return self._process_list(element, context)

        # Ссылки
        if element.name in ["a", "ac:link"]:
            return self._process_link(element, context)

        # Время
        if element.name == "time" and element.get("datetime"):
            return element["datetime"]

        # Параграфы и div/span
        if element.name in ["p", "div", "span"]:
            return self._process_text_container(element, context)

        # Confluence элементы
        if element.name in ["ac:rich-text-body", "ac:layout", "ac:layout-section", "ac:layout-cell"]:
            return self._process_confluence_container(element, context)

        # Ячейки таблицы
        if element.name in ["td", "th"]:
            return self._process_table_cell(element, context)

        # Элементы списка
        if element.name == "li":
            return self._process_list_item(element, context)

        # По умолчанию - обрабатываем как контейнер
        return self._process_text_container(element, context)

    def _should_include_element(self, element: Tag) -> bool:
        """Определяет, должен ли элемент быть включен на основе цветовой политики"""
        if self.config.include_colored:
            return True  # Включаем все элементы

        # Для режима "только подтвержденные" строже проверяем цвет
        if self._has_colored_style(element):
            return False  # Исключаем цветные элементы

        if self._is_in_colored_ancestor_chain(element):
            return False  # Исключаем элементы в цветных контейнерах

        return True  # Включаем только подтвержденные элементы

    def _extract_black_elements_from_colored_container(self, element: Tag, context: str) -> str:
        """Ищет только явно черные элементы в цветном контейнере"""
        if not self.config.include_colored:
            approved_parts = []

            for child in element.children:
                if isinstance(child, NavigableString):
                    continue
                elif isinstance(child, Tag):
                    # Проверяем черные цвета напрямую
                    child_style = child.get("style", "").lower()
                    child_is_black = False

                    if "color" in child_style:
                        color_match = re.search(r'color\s*:\s*([^;]+)', child_style)
                        if color_match:
                            color_value = color_match.group(1).strip()
                            child_is_black = self._is_black_color(color_value)

                    if child_is_black:
                        # Черный дочерний элемент - извлекаем напрямую
                        child_text = child.get_text(strip=True)
                        if child_text:
                            approved_parts.append(child_text)
                    elif self._has_colored_style(child):
                        # Цветной дочерний элемент - рекурсивно ищем в нем черные части
                        child_text = self._extract_black_elements_from_colored_container(child, context)
                        if child_text:
                            approved_parts.append(child_text)
                    else:
                        # Элемент без цвета - обрабатываем как обычно
                        child_text = self._process_element(child, context)
                        if child_text:
                            approved_parts.append(child_text)

            # Соединяем БЕЗ лишних пробелов
            result = "".join(approved_parts)
            result = re.sub(r'\s+', ' ', result)
            return result.strip()

        return ""

    def _has_colored_style(self, element: Tag) -> bool:
        """Проверяет, имеет ли элемент цветной стиль"""
        style = element.get("style", "").lower()
        if not style or "color" not in style:
            return False

        color_match = re.search(r'color\s*:\s*([^;]+)', style)
        if not color_match:
            return False

        color_value = color_match.group(1).strip()
        return not self._is_black_color(color_value)

    def _is_black_color(self, color_value: str) -> bool:
        """Проверяет, является ли цвет черным"""
        color_value = color_value.strip().lower()
        black_colors = {
            'black', '#000', '#000000',
            'rgb(0,0,0)', 'rgb(0, 0, 0)',
            'rgba(0,0,0,1)', 'rgba(0, 0, 0, 1)',
            'rgb(51,51,0)', 'rgb(51, 51, 0)',
            'rgb(0,51,0)', 'rgb(0, 51, 0)',
            'rgb(0,51,102)', 'rgb(0, 51, 102)',
            'rgb(51,51,51)', 'rgb(51, 51, 51)',
            'rgb(23,43,77)', 'rgb(23, 43, 77)'
        }
        return color_value in black_colors

    def _is_in_colored_ancestor_chain(self, element: Tag) -> bool:
        """Проверяет, есть ли цветные предки у элемента"""
        if self.config.include_colored:
            return False  # В режиме "все фрагменты" не проверяем предков

        current = element.parent
        while current and isinstance(current, Tag):
            if current.name == "ac:rich-text-body":
                break
            if self._has_colored_style(current):
                return True
            current = current.parent
        return False

    def _is_ignored_element(self, element: Tag) -> bool:
        """Проверяет, должен ли элемент игнорироваться"""
        # Зачеркнутый текст
        if element.name == "s":
            return True

        # Jira макросы
        if element.name == "ac:structured-macro" and element.get("ac:name") == "jira":
            return True

        if (element.name == "ac:parameter" and element.parent and
                element.parent.name == "ac:structured-macro" and
                element.parent.get("ac:name") == "jira"):
            return True

        return False

    def _process_header(self, element: Tag, context: str) -> str:
        """Обработка заголовков с префиксами"""
        if not self.config.format_headers:
            return self._process_text_container(element, context)

        level = int(element.name[1])
        prefix = "#" * level
        content = self._process_children(element, context)

        if content.strip():
            return f"{prefix} {content.strip()}"
        return ""

    def _process_table(self, element: Tag, context: str) -> str:
        """Обработка таблиц"""
        if not self.config.format_tables:
            return self._process_text_container(element, context)

        # Получаем строки таблицы
        rows = element.find_all("tr", recursive=False)
        if not rows:
            tbody = element.find("tbody")
            thead = element.find("thead")
            if tbody:
                rows.extend(tbody.find_all("tr", recursive=False))
            if thead:
                rows.extend(thead.find_all("tr", recursive=False))

        if not rows:
            return ""

        table_lines = []
        has_headers = False

        for i, row in enumerate(rows):
            cells = row.find_all(["td", "th"], recursive=False)
            row_data = []

            is_header_row = all(cell.name == "th" for cell in cells)

            for cell in cells:
                cell_content = self._process_table_cell(cell, "table_cell")

                # Обработка атрибутов объединения ячеек
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

            # Формирование строки таблицы
            if is_header_row and not has_headers:
                table_lines.append("| " + " | ".join(row_data) + " |")
                table_lines.append("|" + "|".join([" --- " for _ in row_data]) + "|")
                has_headers = True
            else:
                table_lines.append("| " + " | ".join(row_data) + " |")

        table_content = "\n".join(table_lines) if table_lines else ""

        if table_content.strip():
            return f"**Таблица:**\n{table_content}"
        return ""

    def _process_table_cell(self, element: Tag, context: str) -> str:
        """Обработка ячейки таблицы"""
        # Проверяем на вложенные таблицы
        nested_table = element.find("table")

        if nested_table:
            return self._process_cell_with_nested_table(element, nested_table, context)

        # Проверяем, есть ли структурные элементы (заголовки, списки)
        structural_elements = element.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "div", "p"],
                                               recursive=False)

        if len(structural_elements) > 0:
            # Если есть структурные элементы - используем контейнерную обработку для разделения
            cell_parts = self._process_container(element)
            if cell_parts:
                return "\n".join(cell_parts)
            else:
                # Fallback
                return self._process_children(element, "table_cell")
        else:
            # Простая ячейка без структурных элементов - обрабатываем как обычно
            return self._process_children(element, "table_cell")

    def _process_cell_with_nested_table(self, cell: Tag, nested_table: Tag, context: str) -> str:
        """Обработка ячейки с вложенной таблицей"""
        result_parts = []

        # Текст до таблицы
        text_before = ""
        for child in cell.children:
            if child == nested_table:
                break
            if isinstance(child, NavigableString):
                text_before += str(child)
            elif isinstance(child, Tag) and child.name != "table":
                text_before += self._process_element(child, "table_cell")

        if text_before.strip():
            result_parts.append(text_before.strip())

        # Вложенная таблица как HTML
        nested_html = self._process_nested_table_to_html(nested_table)
        if nested_html:
            result_parts.append(f"**Таблица:** {nested_html}")

        # Текст после таблицы
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
                    text_after += self._process_element(child, "table_cell")

        if text_after.strip():
            result_parts.append(text_after.strip())

        return " ".join(result_parts)

    def _process_nested_table_to_html(self, table: Tag) -> str:
        """Преобразование вложенной таблицы в HTML"""
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

                # Атрибуты ячейки
                attrs = []
                if cell.get("rowspan") and int(cell.get("rowspan", 1)) > 1:
                    attrs.append(f'rowspan="{cell["rowspan"]}"')
                if cell.get("colspan") and int(cell.get("colspan", 1)) > 1:
                    attrs.append(f'colspan="{cell["colspan"]}"')

                attrs_str = " " + " ".join(attrs) if attrs else ""

                # Содержимое ячейки
                cell_content = self._process_children(cell, "nested_table_cell")
                row_parts.append(f"<{tag_name}{attrs_str}>{cell_content}</{tag_name}>")

            row_parts.append("</tr>")
            html_parts.append("".join(row_parts))

        html_parts.append("</table>")
        return "".join(html_parts)

    def _process_list(self, element: Tag, context: str, indent_level: int = 0) -> str:
        """Обработка списков с поддержкой вложенности"""
        if not self.config.format_lists:
            return self._process_text_container(element, context)

        list_items = []
        indent = "    " * indent_level

        # Определяем маркеры для списка
        if element.name == "ul":
            markers = ["-", "*", "+"]
            marker = markers[indent_level % len(markers)]
        else:
            marker = None

        item_counter = 1

        for li in element.find_all("li", recursive=False):
            # ДОБАВЛЕНИЕ: Проверяем, должен ли элемент списка быть включен
            if not self._should_include_element(li):
                # В режиме "только подтвержденные" ищем черные элементы в цветном li
                if not self.config.include_colored:
                    black_content = self._extract_black_elements_from_colored_container(li, context)
                    if black_content.strip():
                        if element.name == "ul":
                            list_items.append(f"{indent}{marker} {black_content.strip()}")
                        else:
                            list_items.append(f"{indent}{item_counter}. {black_content.strip()}")
                            item_counter += 1
                continue  # Пропускаем этот элемент

            # Обрабатываем основное содержимое элемента (без вложенных списков)
            item_content = self._process_list_item_content(li, context, indent_level)

            if item_content.strip():
                if element.name == "ul":
                    list_items.append(f"{indent}{marker} {item_content.strip()}")
                else:
                    list_items.append(f"{indent}{item_counter}. {item_content.strip()}")
                    item_counter += 1

            # Обработка вложенных списков
            nested_lists = li.find_all(["ul", "ol"], recursive=False)
            for nested_list in nested_lists:
                nested_content = self._process_list(nested_list, context, indent_level + 1)
                if nested_content:
                    list_items.append(nested_content)

        result = "\n".join(list_items)

        # НЕ применяем content cleanup к спискам, чтобы сохранить отступы
        if self.config.clean_brackets:
            result = self._clean_triangular_brackets(result)

        return result

    def _process_list_item_content(self, li: Tag, context: str, indent_level: int) -> str:
        """Обработка содержимого элемента списка (без вложенных списков)"""
        content_parts = []

        for child in li.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text:
                    content_parts.append(text)
            elif isinstance(child, Tag):
                if child.name in ["ul", "ol"]:
                    # Вложенные списки обрабатываются отдельно
                    continue
                else:
                    # ИСПРАВЛЕНИЕ: Применяем цветовую фильтрацию к дочерним элементам
                    if self._should_include_element(child):
                        child_content = self._process_element(child, context)
                        if child_content.strip():
                            content_parts.append(child_content.strip())
                    elif not self.config.include_colored:
                        # В режиме "только подтвержденные" ищем черные элементы в цветных контейнерах
                        black_content = self._extract_black_elements_from_colored_container(child, context)
                        if black_content.strip():
                            content_parts.append(black_content.strip())

        return " ".join(content_parts)

    def _process_list_item(self, element: Tag, context: str) -> str:
        """Обработка элемента списка (когда li обрабатывается отдельно)"""
        return self._process_children(element, context)

    def _process_link(self, element: Tag, context: str) -> str:
        """Обработка ссылок"""
        # В режиме "только подтвержденные" применяем дополнительную логику
        if not self.config.include_colored:
            if self._is_in_colored_ancestor_chain(element):
                return ""

            # Для ссылок в ячейках таблиц применяем анализ соседних элементов
            if context in ["table_cell", "nested_table_cell"]:
                if not self._analyze_link_neighbors(element):
                    return ""

        # Извлечение текста ссылки
        ri_page = element.find("ri:page")
        if ri_page and ri_page.get("ri:content-title"):
            return f'[{ri_page["ri:content-title"]}]'
        elif element.get_text(strip=True):
            return f'[{element.get_text(strip=True)}]'
        else:
            return ""

    def _analyze_link_neighbors(self, link_element: Tag) -> bool:
        """Анализ соседних блоков ссылки для определения её статуса"""
        if not link_element.parent:
            return True

        parent = link_element.parent
        all_children = list(parent.children)

        try:
            link_index = all_children.index(link_element)
        except ValueError:
            return True

        # Ищем ближайший текстовый блок слева и справа
        left_status = self._get_neighbor_block_status(all_children, link_index, -1)
        right_status = self._get_neighbor_block_status(all_children, link_index, 1)

        # Применяем правила анализа
        if left_status is None and right_status is None:
            return True
        elif left_status is None:
            left_status = right_status
        elif right_status is None:
            right_status = left_status

        # Если оба соседних блока цветные - ссылка исключается
        return not (left_status and right_status)

    def _get_neighbor_block_status(self, children: list, start_index: int, direction: int) -> Optional[bool]:
        """Получает статус соседнего блока (True=цветной, False=подтвержденный, None=нет блока)"""
        step = direction
        for i in range(start_index + step, len(children) if direction > 0 else -1, step):
            if direction < 0 and i < 0:
                break

            child = children[i]
            status = self._get_text_block_color_status(child)
            if status is not None:
                return status

        return None

    def _get_text_block_color_status(self, element) -> Optional[bool]:
        """Определяет статус текстового блока (True=цветной, False=подтвержденный, None=нет текста)"""
        if isinstance(element, NavigableString):
            text = str(element).strip()
            return False if text else None  # Текстовый узел без стиля = подтвержденный

        if isinstance(element, Tag):
            if element.name in ["br", "ac:structured-macro"]:
                return None

            text_content = element.get_text(strip=True)
            if not text_content:
                return None

            return self._has_colored_style(element)

        return None

    def _process_text_container(self, element: Tag, context: str) -> str:
        """Обработка текстовых контейнеров (p, div, span)"""
        # Для div проверяем наличие заголовков внутри
        if element.name == "div":
            inner_headers = element.find_all(["h1", "h2", "h3", "h4", "h5", "h6"], recursive=False)
            if inner_headers:
                # Если есть заголовки - обрабатываем как контейнер
                return self._process_confluence_container(element, context)

        return self._process_children(element, context)

    def _process_confluence_container(self, element: Tag, context: str) -> str:
        """Обработка Confluence контейнеров"""
        nested_parts = self._process_container(element)
        return "\n\n".join(nested_parts)

    def _process_children(self, element: Tag, context: str) -> str:
        """Рекурсивная обработка дочерних элементов"""
        result_parts = []
        prev_was_tag = False

        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text:
                    result_parts.append(text)
                    prev_was_tag = False
            elif isinstance(child, Tag):
                child_content = self._process_element(child, context)
                if child_content:
                    # Добавляем пробел между тегами, если нужно
                    if (prev_was_tag and result_parts and
                            not result_parts[-1].endswith(' ') and
                            not child_content.startswith(' ')):
                        result_parts.append(' ')
                    result_parts.append(child_content)
                    prev_was_tag = True

        result = "".join(result_parts)
        return self._apply_content_cleanup(result)

    def _process_text_node(self, text: str, context: str) -> str:
        """Обработка текстового узла"""
        return text  # Возвращаем как есть, очистка будет применена позже

    def _apply_content_cleanup(self, content: str) -> str:
        """Применение очистки контента"""
        if not self.config.normalize_spacing:
            return content

        # ИСПРАВЛЕНИЕ: НЕ нормализуем пробелы для списков (сохраняем отступы)
        if re.search(r'[-*+]\s|\d+\.\s', content):
            # Это содержимое списка - только очищаем треугольные скобки
            if self.config.clean_brackets:
                content = self._clean_triangular_brackets(content)
            return content.strip()

        # Для обычного содержимого применяем полную очистку
        content = re.sub(r'[ \t]{2,}', ' ', content)

        if self.config.clean_brackets:
            content = self._clean_triangular_brackets(content)

        content = re.sub(r'\n+', ' ', content)
        content = re.sub(r' {2,}', ' ', content)

        # Очистка пробелов вокруг пунктуации
        content = re.sub(r'\]\s+\.', '].', content)
        content = re.sub(r'>\s+\.', '>.', content)

        return content.strip()

    def _clean_triangular_brackets(self, content: str) -> str:
        """Очистка содержимого треугольных скобок"""
        content = re.sub(r'<\s*([^<>]*?)\s*>', lambda m: f'<{self._clean_bracket_content(m.group(1))}>', content)
        content = re.sub(r'<\s*>', '<>', content)
        return content

    def _clean_bracket_content(self, content: str) -> str:
        """Умная очистка содержимого треугольных скобок"""
        if not content:
            return ''

        # Убираем лишние пробелы в начале и конце
        content = content.strip()

        # Нормализуем множественные пробелы
        content = re.sub(r'\s+', ' ', content)

        # Правильная обработка кавычек
        content = re.sub(r'"\s+', '"', content)  # " текст -> "текст
        content = re.sub(r'\s+"', '"', content)  # текст " -> текст"
        content = re.sub(r'(\w)"', r'\1 "', content)  # слово"текст -> слово "текст

        # Обработка квадратных скобок
        content = re.sub(r'\[\s+', '[', content)  # [ текст -> [текст
        content = re.sub(r'\s+\]', ']', content)  # текст ] -> текст]

        return content

    def _apply_final_cleanup(self, result: str) -> str:
        """Финальная очистка результата"""
        # Нормализация множественных переносов строк
        result = re.sub(r'\n\s*\n+', '\n\n', result)

        # Финальная очистка пробелов перед пунктуацией
        result = re.sub(r'\]\s+\.', '].', result)
        result = re.sub(r'>\s+\.', '>.', result)

        return result


# Фабричные функции для создания экстракторов
def create_all_fragments_extractor() -> ContentExtractor:
    """Создает экстрактор для всех фрагментов"""
    config = ExtractionConfig(include_colored=True)
    return ContentExtractor(config)


def create_approved_fragments_extractor() -> ContentExtractor:
    """Создает экстрактор для подтвержденных фрагментов"""
    config = ExtractionConfig(include_colored=False)
    return ContentExtractor(config)