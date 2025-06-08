# app/filter_approved_fragments.py

import logging
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup, Tag, NavigableString
import re


def is_strictly_black_color(color_value: str) -> bool:
    """Проверяет черный цвет и часть цветов из верхней строки редактора Confluence"""
    color_value = color_value.strip().lower()
    black_colors = {
        'black', '#000', '#000000',
        'rgb(0,0,0)', 'rgb(0, 0, 0)',
        'rgba(0,0,0,1)', 'rgba(0, 0, 0, 1)',
        'rgb(51,51,0)', 'rgba(51, 51, 0)',
        'rgb(0,51,0)', 'rgba(0, 51, 0)',
        'rgb(0,51,102)', 'rgba(0, 51, 102)',
        'rgb(51,51,51)', 'rgba(51, 51, 51)'
    }
    return color_value in black_colors


def filter_approved_fragments(html: str) -> str:
    """
    Извлекает подтвержденные фрагменты с гибридной разметкой (Markdown + HTML)
    """
    logging.debug("[filter_approved_fragments] <- {%s}", html)

    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Извлекаем содержимое expand блоков
    for expand in soup.find_all("ac:structured-macro", {"ac:name": "expand"}):
        rich_text_body = expand.find("ac:rich-text-body")
        if rich_text_body:
            expand.replace_with(rich_text_body)

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
                    # ВОЗВРАЩАЕМСЯ К ПРОСТОМУ ИЗВЛЕЧЕНИЮ ТЕКСТА
                    return element.get_text(strip=True)

        # Рекурсивно ищем в дочерних элементах
        approved_parts = []
        for child in element.children:
            if isinstance(child, Tag):
                child_text = extract_black_elements_from_colored_container(child)
                if child_text:
                    approved_parts.append(child_text)

        return " ".join(approved_parts)

    def extract_approved_text(element) -> str:
        """Извлекает только подтвержденный текст из элемента"""
        if isinstance(element, NavigableString):
            return str(element).strip()

        if not isinstance(element, Tag):
            return ""

        # Игнорируем зачеркнутый текст всегда
        if element.name == "s":
            return ""

        # ИСПРАВЛЕНИЕ 1: Игнорируем Jira макросы всегда и ВСЕ их параметры
        if element.name == "ac:structured-macro" and element.get("ac:name") == "jira":
            return ""

        # ИСПРАВЛЕНИЕ 2: Игнорируем ВСЕ параметры Jira макросов
        if element.name == "ac:parameter" and element.parent and \
                element.parent.name == "ac:structured-macro" and \
                element.parent.get("ac:name") == "jira":
            return ""

        # Время - только если элемент подтвержден
        if element.name == "time" and element.get("datetime"):
            if not has_colored_style(element) and not is_in_colored_ancestor_chain(element):
                return element["datetime"]
            return ""

        # Обработка ссылок - ВОЗВРАЩАЕМСЯ К ПРОСТОЙ ЛОГИКЕ
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

        # Если элемент сам цветной - ищем черные дочерние элементы
        if has_colored_style(element):
            return extract_black_elements_from_colored_container(element)

        # Элемент не имеет цветного стиля, но проверяем предков
        if is_in_colored_ancestor_chain(element):
            return ""

        # Рекурсивно обрабатываем дочерние элементы
        child_texts = []
        for child in element.children:
            child_text = extract_approved_text(child)
            if child_text.strip():
                child_texts.append(child_text.strip())

        return " ".join(child_texts)

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
            # Обычная ячейка без вложенной таблицы
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
            return " ".join(approved_parts)

        # ИСПРАВЛЕНИЕ: Убираем проверку цветных предков для вложенных таблиц
        # Это позволит обрабатывать черные ссылки в цветных ячейках

        # Рекурсивно обрабатываем дочерние элементы
        child_texts = []
        for child in element.children:
            child_text = extract_approved_text_for_nested_table(child)
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


    def process_list(list_element: Tag) -> str:
        """Обрабатывает список"""
        list_items = []
        for li in list_element.find_all("li", recursive=False):
            item_text = extract_approved_text(li)
            if item_text.strip():
                prefix = "- " if list_element.name == "ul" else "1. "
                list_items.append(f"{prefix}{item_text.strip()}")
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
                # Списки
                list_content = process_list(element)
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

        return result_parts

    # Основная обработка
    approved_fragments = process_elements_sequentially(soup)
    result = "\n\n".join(approved_fragments)
    result = re.sub(r'\n\s*\n+', '\n\n', result)
    result = re.sub(r'[ \t]+', ' ', result)

    logging.debug("[filter_approved_fragments] -> {%s}", result)
    return result.strip()


# Тестирование
if __name__ == "__main__":
    def test_pointwise_fixes():
        """Тест точечных исправлений"""

        html_content = '''<p class="auto-cursor-target"><br /></p><ac:structured-macro ac:name="expand" ac:schema-version="1" ac:macro-id="c1418da8-49b0-482f-baf5-f57c89d06c9b"><ac:parameter ac:name="title">История изменений</ac:parameter><ac:rich-text-body><h1 class="auto-cursor-target">История изменений</h1><table class="wrapped fixed-width"><colgroup><col style="width: 10.3655%;" /><col style="width: 46.9704%;" /><col style="width: 25.6885%;" /><col style="width: 16.9754%;" /></colgroup><tbody><tr><th><span style="color: rgb(0,51,102);">Дата</span></th><th><span style="color: rgb(0,51,102);">Описание</span></th><th>Автор</th><th><span style="color: rgb(0,51,102);">Задача в JIRA</span></th></tr><tr><td style="text-align: left;"><div class="content-wrapper"><p><time datetime="2024-12-20" />&nbsp;</p></div></td><td style="text-align: left;"><span style="color: rgb(255,102,0);">Красные текст. Открытие <ac:link><ri:page ri:content-title="[КК_СК] ЭФ Клиента &quot;Фильтр списка карт&quot;" /></ac:link></span></td><td style="text-align: left;"><div class="content-wrapper"><p><ac:link><ri:user ri:userkey="8a69e14184d815fe0185a5cc43be0016" /></ac:link>&nbsp;</p></div></td><td><div class="content-wrapper"><p><br /></p></div></td></tr><tr><td><div class="content-wrapper"><p><span style="color: rgb(0,51,102);"><em>01.12.2021</em></span></p></div></td><td><span style="color: rgb(0,51,102);">Первичное опиисание</span></td><td><div class="content-wrapper"><p><em><ac:link><ri:user ri:userkey="8a69e14184d815fe0185a5cc43be0016" /></ac:link> </em></p></div></td><td><div class="content-wrapper"><p><span style="color: rgb(0,51,102);"><ac:structured-macro ac:name="jira" ac:schema-version="1" ac:macro-id="8c161b0d-5c28-4a30-8cf5-8f8293f2fb6f"><ac:parameter ac:name="server">Jira</ac:parameter><ac:parameter ac:name="columnIds">issuekey,summary,issuetype,created,updated,duedate,assignee,reporter,priority,status,resolution</ac:parameter><ac:parameter ac:name="columns">key,summary,type,created,updated,due,assignee,reporter,priority,status,resolution</ac:parameter><ac:parameter ac:name="serverId">d16f6246-3bab-3486-bdb2-a413c93ba7a0</ac:parameter><ac:parameter ac:name="key">GBO-18088</ac:parameter></ac:structured-macro></span></p></div></td></tr></tbody></table><p class="auto-cursor-target"><br /></p></ac:rich-text-body></ac:structured-macro><h1 class="auto-cursor-target">Описание</h1><p>В данном документе приведены контроли реквизитов запроса, используемые:</p><ul><li>Группа 1: подтвержденная группа с линком <ac:link><ri:page ri:content-title="OLD - /business-cards/get-page - ЭКО_Получение списка корпоративных карт" /></ac:link>.&nbsp;</li><li><span style="color: rgb(255,102,0);">Группа 2: красная группа с линком <ac:link><ri:page ri:content-title="[КК_СК] ЭФ Клиента &quot;Фильтр списка карт&quot;" /></ac:link>&nbsp;</span></li></ul><h1>Проверки</h1><p><br /></p><table class="fixed-width wrapped" style="width: 58.5092%;"><colgroup><col style="width: 6.88673%;" /><col style="width: 16.2669%;" /><col style="width: 19.7103%;" /><col style="width: 17.573%;" /><col style="width: 39.5393%;" /></colgroup><tbody><tr><th>Hdr <span style="color: rgb(255,0,0);">1</span></th><th><span style="color: rgb(0,0,0);">Hdr 2&nbsp;</span></th><th>Hdr 3</th><th><s>Hdr</s> 4</th><th><span style="color: rgb(255,0,0);">CHdr</span> 6</th></tr><tr><td rowspan="2">1</td><td rowspan="2"><p>Txt 2.1.1 <span style="color: rgb(255,0,0);">Ctxt 2.1.2</span>&nbsp;<strong>BTxt 2.1.3 </strong>&nbsp;NTxt 2.1.4</p></td><td>Td 3.1 <span style="color: rgb(255,0,0);">Ctd 3.1</span> LTxt 3/</td><td><span style="color: rgb(255,0,0);">CTxt 4.1.1</span> UTxt 4.1.2</td><td><br /></td></tr><tr><td rowspan="2"><p><span style="color: rgb(255,0,0);"><s>UCtxt 3..2.1</s></span> <s>UTxt 3.2.2 <strong>UBTxt 3.2.3</strong></s></p>Txt 3.1=строка</td><td><p><span style="color: rgb(255,0,0);"><strong>CTxt 4.2.1</strong></span>&nbsp;<ac:link><ri:page ri:content-title="Клиент Банка" /></ac:link><span style="color: rgb(204,153,255);">.<span style="color: rgb(255,0,0);">CTxt 4.2.3.</span></span></p></td><td><br /></td></tr><tr><td rowspan="2">2</td><td rowspan="2"><p><span style="color: rgb(204,153,255);"><span style="color: rgb(255,0,0);">Ctxt 2.2</span> <span style="color: rgb(0,0,0);">Txt 2.2.2</span></span></p><p><br /></p></td><td><span style="color: rgb(255,0,0);">Txt_4.3.1 <span style="color: rgb(0,0,0);">Txt_4.3.1</span></span></td><td><span style="color: rgb(255,0,0);">CTxt_6.3.1 <span style="color: rgb(0,0,0);">Txt_6.3.2</span></span></td></tr><tr><td><span style="color: rgb(204,153,255);"><span style="color: rgb(255,0,0);">Ctxt3.3=строка</span></span></td><td><p style="text-align: left;"><strong>BTxt 4.4.1&nbsp; <ac:link><ri:page ri:content-title="Клиент Банка" /></ac:link>.</strong> СTxt 4.3.2 <ac:link><ri:page ri:content-title="Клиент Банка" /></ac:link><span style="color: rgb(204,153,255);">.</span></p></td><td><p>CTxt6.4.1:</p><table data-mce-resize="false"><colgroup class=""><col class="" /><col class="" /><col class="" /></colgroup><tbody class=""><tr class=""><th>заг_1</th><th><span style="color: rgb(153,51,0);">заг_2</span></th><th><span style="color: rgb(0,0,0);">заг_3</span></th></tr><tr class=""><td><p>Вл_Txt_1_1 <span style="color: rgb(255,0,0);">Вл_Txt_1_2</span></p><p><strong><span style="color: rgb(0,0,0);">Вл_BTxt_1.1.3</span></strong></p><p><span style="color: rgb(255,0,0);"><strong><ac:link><ri:page ri:content-title="[ОНК] Страница 1" /></ac:link></strong></span></p></td><td rowspan="2"><p>Вл_Txt_2_1 <span style="color: rgb(255,0,0);"><strong><ac:link><ri:page ri:content-title="[ОНК] Страница 1" /></ac:link></strong></span></p><p><span style="color: rgb(255,0,0);">Вл_Txt_2_2</span></p>&nbsp;<strong>BTxt_2_3</strong></td><td><p>Вл_Txt_3_1</p></td></tr><tr class=""><td>Вл_Txt_1_2_2</td><td><p><span style="color: rgb(255,0,0);">Вл_Txt_3_2_1</span></p><p><strong>Вл_BTxt_3_2_2</strong></p></td></tr></tbody></table><p class="auto-cursor-target"><br /></p></td></tr></tbody></table><p class="auto-cursor-target"><br /></p>'''

        result = filter_approved_fragments(html_content)

        print("=" * 80)
        print(f"Результат:")
        print(result)
        print("=" * 80)


    # Запускаем тест
    test_pointwise_fixes()