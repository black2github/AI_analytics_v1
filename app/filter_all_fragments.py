# app/filter_all_fragments.py

import logging
from typing import List
from bs4 import BeautifulSoup, Tag, NavigableString
import re
import sys
import io

# Настройка кодировки для Windows консоли
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def filter_all_fragments(html: str) -> str:
    """
    Извлекает все фрагменты из HTML с гибридной разметкой (Markdown + HTML)
    без учета цвета элементов
    """
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
            # Сначала извлекаем текст ДО таблицы
            text_before = ""
            for child in cell.children:
                if child == nested_table:
                    break
                if isinstance(child, NavigableString):
                    text_before += str(child)
                elif isinstance(child, Tag) and child.name != "table":
                    text_before += extract_all_text(child)

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
                        text_after += extract_all_text(child)

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

    def process_list(list_element: Tag) -> str:
        """Обрабатывает список"""
        list_items = []
        for li in list_element.find_all("li", recursive=False):
            item_text = extract_all_text(li)
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
                # Списки
                list_content = process_list(element)
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

    return result.strip()


# Тестирование
if __name__ == "__main__":
    def test_all_fragments():
        """Тест извлечения всех фрагментов"""

        html_content = '''<ac:layout><ac:layout-section ac:type="single"><ac:layout-cell><p class="auto-cursor-target"><strong>История изменений:</strong></p><table class="fixed-table wrapped"><colgroup><col style="width: 207.0px;" /><col style="width: 462.0px;" /><col style="width: 235.0px;" /><col style="width: 289.0px;" /></colgroup><tbody><tr><th>Дата</th><th>Описание</th><th>Автор</th><th>Задача в JIRA</th></tr><tr><td><div class="content-wrapper"><p><time datetime="2025-04-22" />&nbsp;</p></div></td><td><span style="color: rgb(0,204,255);">Переход на УФ v.2.2 и добавление групповой подписи заявок на выпуск карт</span></td><td><ac:link><ri:user ri:userkey="8a69e14184d815fe0185bb32d0520019" /></ac:link>&nbsp;</td><td><div class="content-wrapper"><p><ac:structured-macro ac:macro-id="b164f522-c530-40a4-b108-8dfe92da71c5" ac:name="jira" ac:schema-version="1"><ac:parameter ac:name="server">Jira</ac:parameter><ac:parameter ac:name="serverId">d16f6246-3bab-3486-bdb2-a413c93ba7a0</ac:parameter><ac:parameter ac:name="key">GBO-124016</ac:parameter></ac:structured-macro></p></div></td></tr><tr><td><div class="content-wrapper"><p><time datetime="2024-11-11" />&nbsp;</p></div></td><td><span style="color: rgb(0,51,102);">Перенос уведомления об успешном подписании в аналитику самой ЭФ</span></td><td><ac:link><ri:user ri:userkey="8a69e14184d815fe0185bb32d0520019" /></ac:link>&nbsp;</td><td><div class="content-wrapper"><p><ac:structured-macro ac:macro-id="d032460e-6a56-4848-9883-4066e7c16e47" ac:name="jira" ac:schema-version="1"><ac:parameter ac:name="server">Jira</ac:parameter><ac:parameter ac:name="serverId">d16f6246-3bab-3486-bdb2-a413c93ba7a0</ac:parameter><ac:parameter ac:name="key">GBO-104829</ac:parameter></ac:structured-macro></p></div></td></tr><tr><td><div class="content-wrapper"><p><time datetime="2024-04-19" />&nbsp;</p></div></td><td><span style="color: rgb(0,51,102);">Мапинг кода офиса выдачи</span></td><td><ac:link><ri:user ri:userkey="8a69e14184d815fe0185bb32d0520019" /></ac:link>&nbsp;</td><td><div class="content-wrapper"><p><ac:structured-macro ac:macro-id="88f13280-ea80-47be-b181-cea538b60a6d" ac:name="jira" ac:schema-version="1"><ac:parameter ac:name="server">Jira</ac:parameter><ac:parameter ac:name="serverId">d16f6246-3bab-3486-bdb2-a413c93ba7a0</ac:parameter><ac:parameter ac:name="key">GBO-80864</ac:parameter></ac:structured-macro></p></div></td></tr><tr><td><div class="content-wrapper"><p><time datetime="2023-08-01" />&nbsp;</p></div></td><td>Описан переход на <ac:link><ri:page ri:content-title="[ЭП] Логика работы универсальной функции электронной подписи v2.1" /></ac:link></td><td><ac:link><ri:user ri:userkey="8a69f5997f6454ef0180d1b149270055" /></ac:link>&nbsp;</td><td><div class="content-wrapper"><p><ac:structured-macro ac:macro-id="3817b2f0-9f2d-45e2-b3a0-d3457faf01ea" ac:name="jira" ac:schema-version="1"><ac:parameter ac:name="server">Jira</ac:parameter><ac:parameter ac:name="serverId">d16f6246-3bab-3486-bdb2-a413c93ba7a0</ac:parameter><ac:parameter ac:name="key">GBO-57388</ac:parameter></ac:structured-macro></p></div></td></tr><tr><td><div class="content-wrapper"><p><time datetime="2022-03-14" />&nbsp;</p></div></td><td>Описание функции</td><td><div class="content-wrapper"><p><ac:link><ri:user ri:userkey="8a69f44a7daffdab017dd86073010006" /></ac:link>&nbsp;</p></div></td><td><div class="content-wrapper"><p><ac:structured-macro ac:macro-id="e6ee63af-c475-4256-b8be-47b10a0dc0c8" ac:name="jira" ac:schema-version="1"><ac:parameter ac:name="server">Jira</ac:parameter><ac:parameter ac:name="columnIds">issuekey,summary,issuetype,created,updated,duedate,assignee,reporter,priority,status,resolution</ac:parameter><ac:parameter ac:name="columns">key,summary,type,created,updated,due,assignee,reporter,priority,status,resolution</ac:parameter><ac:parameter ac:name="serverId">d16f6246-3bab-3486-bdb2-a413c93ba7a0</ac:parameter><ac:parameter ac:name="key">GBO-21374</ac:parameter></ac:structured-macro></p></div></td></tr></tbody></table><p class="auto-cursor-target"><br /></p></ac:layout-cell></ac:layout-section><ac:layout-section ac:type="single"><ac:layout-cell><p class="auto-cursor-target"><strong>Описание функции:</strong></p><table class="fixed-table wrapped"><colgroup><col style="width: 207.0px;" /><col style="width: 990.0px;" /></colgroup><tbody><tr><td colspan="1"><strong>Доступность функции:</strong></td><td colspan="1"><p>Доступность функции зависит от:</p><ul><li>Роли пользователя (см. <ac:link><ri:page ri:content-title="[ЦРМ] Ролевая модель клиента" /></ac:link>).</li><li><span style="color: rgb(0,51,102);">От статуса заявки (см. </span><ac:link><ri:page ri:content-title="[КК_ВК] Функции Клиента" /></ac:link>).</li></ul></td></tr><tr><td><strong>Как вызывается функция:</strong></td><td><p style="text-align: left;"><span style="color: rgb(0,51,102);">Раздел &quot;Продукты&quot; &rarr; &quot;Корпоративные карты&quot; на ЭФ<span>&nbsp;</span><a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=353841">Основное окно сотрудника Клиента</a></span><span style="color: rgb(0,51,102);letter-spacing: 0.0px;">:</span></p><ul><li><span style="color: rgb(0,51,102);letter-spacing: 0.0px;">После нажатия кнопки &quot;Подписать и отправить&quot; с </span><span style="color: rgb(255,0,0);letter-spacing: 0.0px;"><ac:link><ri:page ri:content-title="[КК_Заявки] ЭФ Клиента &quot;Журнал заявок&quot;" /></ac:link> <span style="color: rgb(0,51,102);">(для выбранной заявки).</span></span></li><li><span style="letter-spacing: 0.0px;"><ac:link><ri:page ri:content-title="[КК_ВК] ЭФ Клиента: страница &quot;Подтверждение&quot;" ri:space-key="DBOCORPES" /><ac:plain-text-link-body><![CDATA[[КК_ВК] ЭФ Клиента: вкладка "Подтверждение"]]></ac:plain-text-link-body></ac:link>&nbsp;(при создании и редактировании заявки) &rarr; после нажатия кнопки &quot;Подписать и отправить&quot;.</span></li></ul></td></tr><tr><td colspan="1"><strong>Входящие параметры:</strong></td><td colspan="1"><p><span style="color: rgb(0,204,255);">Один из вариантов параметров:</span></p><ul style="text-align: left;"><li><span style="color: rgb(0,204,255);">Либо фильтр, примененный на <a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=42675009">[КК_Заявки] ЭФ Клиента &quot;Фильтр журнала заявок&quot;</a></span></li><li><span style="color: rgb(0,204,255);">Либо массив,&nbsp;состоящий из</span><span> <ac:link><ri:page ri:content-title="[КК_ВК] Заявка на выпуск карты и открытие счета" /></ac:link></span><span>.&lt;</span><span style="color: rgb(23,43,77);">Идентификатор заявки&gt;<span style="color: rgb(0,204,255);"> <s>(обязательный)</s></span></span></li></ul></td></tr><tr><td><strong>Что делает функция:</strong></td><td><p style="text-align: left;"><span style="color: rgb(0,204,255);"><strong>Шаг №0</strong> (выполняется на бэке)<strong>. </strong>Инициализация справочных параметров:</span></p><ul><li><span style="color: rgb(0,204,255);">Для всех элементов массива <ac:link><ri:page ri:content-title="[КК_ВК] Заявка на выпуск карты и открытие счета" /><ac:plain-text-link-body><![CDATA[Заявка на выпуск карты и открытие счета]]></ac:plain-text-link-body></ac:link>.<ac:link><ri:page ri:content-title="[КК_ВК] Выпускаемая карта" /><ac:plain-text-link-body><![CDATA[Выпускаемая карта]]></ac:plain-text-link-body></ac:link> выполняется: </span><br /><span style="color: rgb(0,204,255);"><ac:link><ri:page ri:content-title="[КК_ВК] Выпускаемая карта" /></ac:link>.&lt;Код офиса выдачи&gt; = <a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=328224" rel="nofollow">Подразделение Банка</a>.&lt;Код подразделения&gt; &rarr; <ac:link><ri:page ri:content-title="[КК_ВК] Выпускаемая карта" /><ac:plain-text-link-body><![CDATA[Выпускаемая карта]]></ac:plain-text-link-body></ac:link>.&lt;Ссылка на офис выдачи&gt;.</span></li></ul><p><span style="color: rgb(0,204,255);">Сохраняется заявки.</span></p><p><span style="color: rgb(0,204,255);">Осуществляется переход на шаг №1.</span></p><p style="text-align: left;"><span style="color: rgb(0,204,255);"><strong>Шаг №1. Формирование массива индентификаторов заявок для работы.</strong></span></p><p style="text-align: left;"><span style="color: rgb(0,204,255);">Создается временная переменная&nbsp;<u><em>Массив_идентификаторов</em></u>, которая инициализируется либо массивом идентификаторов, полученным во входящих параметрах, либо идентификаторами заявок, отобранными по условию фильтра, полученному во входящих параметрах.</span></p><p style="text-align: left;"><span style="color: rgb(0,204,255);">Переход на шаг №2.</span></p><p style="text-align: left;"><span style="color: rgb(0,204,255);"><strong>Шаг №2. Проверка количества подписываемых документов.</strong></span></p><p style="margin-left: 40.0px;text-align: left;"><span style="color: rgb(0,204,255);">Выполняется проверка на непревышение количества выбранных элементов&nbsp;в&nbsp;массиве:</span></p><ul style="text-align: left;"><li style="list-style-type: none;"><ul><li style="list-style-type: none;"><ul style="text-align: left;"><li><span style="color: rgb(0,204,255);"><strong>Если&nbsp;</strong>количество&nbsp;элементов в&nbsp;<u><em>Массив_идентификаторов</em></u> &le; <a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=111261500">[Настраиваемые параметры] Корпоративные карты</a>.&lt;CC_att_issue_qty&gt;,&nbsp;<strong>то&nbsp;</strong>проверка пройдена и осуществляется переход на шаг №3,</span></li><li><span style="color: rgb(0,204,255);"><strong>иначе&nbsp;</strong>пользователю отображается модальное окно с текстом: &quot;Выберите не более %<a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=111261500">[Настраиваемые параметры] Корпоративные карты</a>.&lt;CC_att_issue_qty&gt;% заявок для подписи&quot; и кнопкой &quot;Понятно&quot;, при нажатии на которую процесс завершается.</span></li></ul></li></ul></li></ul><p style="text-align: left;"><span style="color: rgb(0,204,255);"><strong>Шаг №3. Проверка полномочий.</strong></span></p><p style="text-align: left;"><span style="color: rgb(0,204,255);">Выполняется контроль <a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=6364001" style="text-decoration: none;" rel="nofollow">Функция проверки в ЕСК наличия полномочий пользователя на подпись документа</a>&nbsp;для заявок с типом &quot;Заявка на выпуск карт и открытие счета&quot;.</span></p><ul style="text-align: left;"><li style="list-style-type: none;"><ul><li style="list-style-type: none;"><ul style="text-align: left;"><li><span style="color: rgb(0,204,255);"><strong>Если&nbsp;</strong>контроль пройден,&nbsp;<strong>то&nbsp;</strong>осуществляется переход на шаг №4,</span></li><li><span style="color: rgb(0,204,255);"><strong>иначе</strong>, пользователю отображается модальное окно с текстом ошибки из описания контроля, и кнопка &quot;Закрыть&quot; - при нажатии осуществляется переход на шаг №6.</span></li></ul></li></ul></li></ul><p style="text-align: left;"><span style="color: rgb(0,204,255);"><strong>Шаг №4</strong><strong>. Проверка статусов подписываемых документов.</strong></span></p><p style="text-align: left;"><span style="color: rgb(0,204,255);">Выполняется проверка, что все заявки, идентификаторы которых входят в&nbsp;<u style="text-align: left;"><em>Массив_идентификаторов,</em></u>&nbsp;имеют статусы <ac:inline-comment-marker ac:ref="5ae2d171-1310-4e50-bba5-958f21d01361">NEW</ac:inline-comment-marker> или SIGN_REQUEST.</span></p><p style="text-align: left;"><span style="color: rgb(0,204,255);">Если хотя бы одна заявка имеет другой статус, то пользователю показывается модальное окно с текстом:</span></p><ul><li style="text-align: left;"><span style="color: rgb(0,204,255);">если в <u style="text-align: left;"><em>Массив_идентификаторов </em></u></span><span style="color: rgb(0,204,255);letter-spacing: 0.0px;">только один элемент, то: &quot;Заявка должна быть в статусе <span style="color: rgb(0,204,255);">&quot;Новый&quot; и &quot;Ожидает подписи&quot;. Заявки в других статусах <ac:inline-comment-marker ac:ref="2a23d4a1-7d1b-4016-91f6-2f278c9fefe0">не требуют подписания.</ac:inline-comment-marker></span><ac:inline-comment-marker ac:ref="0363ba60-0e16-4410-90d7-72972aa57451">&quot; и кнопка &quot;К списку заявок&quot;. Далее выпол</ac:inline-comment-marker>няется <ac:inline-comment-marker ac:ref="ba0857e3-f0c1-4ac7-b944-a700f0e6fb8f">переход к Шагу</ac:inline-comment-marker> 8<ac:inline-comment-marker ac:ref="347fbb2e-f7c0-463e-9713-dc437bf3511c">.</ac:inline-comment-marker></span></li><li style="text-align: left;"><span style="color: rgb(0,204,255);">если в <u><em>Массив_идентификаторов</em></u> несколько элементов, то &quot;Подписание заявок X из Y. Будут подписаны заявки в статусах: &quot;Новый&quot; и &quot;Ожидает подписи&quot;. Заявки в других статусах не требуют подписания.&quot;</span></li></ul><p style="text-align: left;margin-left: 40.0px;"><span style="color: rgb(0,204,255);">Здесь X - количество заявок, имеющих статусы NEW или SIGN_REQUEST, а Y - общее количество выбранных пользователем заявок.</span></p><p style="text-align: left;margin-left: 40.0px;"><span style="color: rgb(0,204,255);">Действия пользователя:</span></p><ul style="text-align: left;"><li style="list-style-type: none;"><ul><li style="list-style-type: none;"><ul><li><span style="color: rgb(0,204,255);">&quot;Подписать и отправить&quot;:&nbsp;идентификаторы&nbsp;заявок, имеющих&nbsp;статус&nbsp;не равный NEW и SIGN_REQUEST исключаются из массива. Выполняется переход на шаг №5.</span></li><li><span style="color: rgb(0,204,255);">&quot;Отменить&quot;: процесс завершается и осуществляется переход на шаг №8</span></li></ul></li></ul></li></ul><p><span style="color: rgb(23,43,77);"><span style="color: rgb(0,51,102);"><strong>Шаг №<span style="color: rgb(0,204,255);">5<s>1</s></span></strong><span style="color: rgb(0,204,255);">. <strong>Подписание заявок с помощью Универсальной функции подписания.</strong></span></span></span></p><p><span style="color: rgb(23,43,77);"><span style="color: rgb(0,51,102);">Осуществляется вызов функции <ac:link><ri:page ri:content-title="[ЭП] Универсальная функция электронной подписи v2.2" /></ac:link><span style="color: rgb(0,204,255);">(нов)<s> <ac:link><ri:page ri:content-title="[ЭП] Универсальная функция электронной подписи v2.1" /></ac:link></s></span></span></span><span style="color: rgb(0,51,102);">.&nbsp;</span><span style="letter-spacing: 0.0px;"><span style="color: rgb(0,51,102);">Зап</span><ac:inline-comment-marker ac:ref="969704fa-ea13-4cb3-bdc4-493a076bd984">олнение параметров вызова функции описано</ac:inline-comment-marker><span style="color: rgb(0,51,102);"> в <ac:link><ri:page ri:content-title="[КК_ВК] Клиент: Параметры вызова универсальной функции электронной подписи v.2.2" ri:space-key="DBOCORPES" /></ac:link><span style="color: rgb(23,43,77);">&nbsp;</span><span style="color: rgb(0,204,255);">(нов)<s> </s></span></span><s><ac:link><ri:page ri:content-title="[КК_ВК] Клиент: Параметры вызова универсальной функции электронной подписи v.2.1" ri:space-key="DBOCORPES" /><ac:link-body><span style="color: rgb(0,204,255);">[КК_ВК] Клиент: Параметры вызова универсальной функции электронной подписи v.2.1</span>.</ac:link-body></ac:link></s></span></p><p style="text-align: left;"><span style="color: rgb(0,204,255);">После выполнения функции осуществляется п<ac:inline-comment-marker ac:ref="83bf9c43-268a-450f-97c8-f6feada8888e">ереход на шаг №7</ac:inline-comment-marker>.</span></p><p><s><span style="color: rgb(0,204,255);"><strong>Если&nbsp;</strong>функция завершилась успешно&nbsp;(<ac:link><ri:page ri:content-title="[ЭП] Исходящие параметры функции подписи v2.1" /></ac:link>.&lt;Код завершения&gt; = 0),</span></s></p><ul><li style="text-align: left;"><s><span style="color: rgb(0,204,255);"><strong>то </strong>осуществляется переход на шаг №2,</span></s></li><li style="text-align: left;"><s><span style="color: rgb(0,204,255);"><strong>иначе </strong>осуществляется переход на шаг №3.</span></s></li></ul><p style="text-align: left;"><s><span style="color: rgb(0,204,255);"><strong>Шаг №2.</strong> Осуществляется сохранение данных о сформированной подписи<span style="letter-spacing: 0.0px;"> заявки на выпуск карты и открытие счета</span><span style="letter-spacing: 0.0px;">:</span></span></s></p><ul style="text-align: left;"><li><s><span style="color: rgb(0,204,255);"><ac:link><ri:page ri:content-title="[КК_ВК] Заявка на выпуск карты и открытие счета" /></ac:link>.&lt;<ac:inline-comment-marker ac:ref="0bfa0a3a-ce67-4c8f-aaa8-dcb3a8c460ea">Идентификатор пользователя, подписавшего заявку</ac:inline-comment-marker>&nbsp;&gt; =&nbsp;<a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=328234" style="text-decoration: none;color: rgb(0,204,255);">Текущий пользователь</a>.&lt;Идентификатор пользователя в экосистеме&gt;.</span></s></li><li><s><span style="color: rgb(0,204,255);"><ac:link><ri:page ri:content-title="[КК_ВК] Заявка на выпуск карты и открытие счета" /></ac:link>.&lt;ФИО пользователя, подписавшего заявку&gt; = <a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=328234" style="text-decoration: none;color: rgb(0,204,255);">Текущий пользователь</a>.&lt;Фамилия&gt; + &quot; &quot; + &lt;Имя&gt; + &quot; &quot; + &lt;Отчество&gt;.</span></s></li><li><s><span style="color: rgb(0,204,255);"><ac:link><ri:page ri:content-title="[КК_ВК] Заявка на выпуск карты и открытие счета" /></ac:link>.&lt;Версия СПП&gt;&nbsp;=&nbsp;Версия СПП, использованная при подписи документа (см. <a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=356307" style="color: rgb(0,204,255);" rel="nofollow">Справочник СПП</a>, раздел &quot;Логика формирования дайджеста для подписи&quot;).</span></s></li><li><s><span style="color: rgb(0,204,255);"><span style="letter-spacing: 0.0px;"><ac:link><ri:page ri:content-title="[КК_ВК] Заявка на выпуск карты и открытие счета" /></ac:link>.&lt;Реквизиты электронной подписи&gt;.&lt;Подпись&gt;</span><span style="letter-spacing: 0.0px;">:&nbsp;</span></span></s><br /><ul><li><s><span style="color: rgb(0,204,255);">&lt;<ac:inline-comment-marker ac:ref="fc4235c4-2def-41b4-a225-dd95964e6771">Дата подписи</ac:inline-comment-marker>&gt; = <ac:link><ri:page ri:content-title="[ЭП] Исходящие параметры функции подписи v2.1" /></ac:link>.&lt;Набор обработанных документов&gt;.<ac:inline-comment-marker ac:ref="67e74504-2fb0-4574-9056-82725f3b7f81">&lt;Набор подписанных данных&gt;.&lt;Дата и время подписи&gt;.</ac:inline-comment-marker></span></s></li><li><s><span style="color: rgb(0,204,255);">&lt;Сертификат ЭП&gt; =&nbsp;<ac:link><ri:page ri:content-title="[ЭП] Исходящие параметры функции подписи v2.1" /></ac:link>.&lt;Локальный идентификатор сертификата&gt;.</span></s></li><li><s><span style="color: rgb(0,204,255);">&lt;Электронная подпись&gt;&nbsp;= <ac:link><ri:page ri:content-title="[ЭП] Исходящие параметры функции подписи v2.1" /></ac:link>.&lt;Набор обработанных документов&gt;.<ac:inline-comment-marker ac:ref="824daf37-9b0d-4c5e-9e33-f9ff373db934">&lt;Набор подписанных данных&gt;.&lt;Значение подписи&gt;</ac:inline-comment-marker>.</span></s></li></ul></li><li><s><span style="color: rgb(0,204,255);"><ac:link><ri:page ri:content-title="[КК_ВК] Заявка на выпуск карты и открытие счета" /></ac:link>.&lt;Идентификатор ЕСК пользователя, подписавшего заявку&gt; = <a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=328234" style="text-decoration: none;color: rgb(0,204,255);" rel="nofollow">Текущий пользователь</a>.&lt;Идентификатор физического лица в ЕСК&gt;.</span></s></li></ul><p style="text-align: left;"><s><span style="color: rgb(0,204,255);">После выполнения сохранения подписей осуществляется переход <ac:inline-comment-marker ac:ref="258aedd1-9c4d-4e3d-99d2-70303c8c8a1f">на шаг </ac:inline-comment-marker><ac:inline-comment-marker ac:ref="258aedd1-9c4d-4e3d-99d2-70303c8c8a1f">№4.</ac:inline-comment-marker></span></s></p><p style="text-align: left;"><strong style="color: rgb(0,51,102);letter-spacing: 0.0px;"><ac:inline-comment-marker ac:ref="9426e08f-4642-4544-9c4a-a8164a80c7e5">Шаг №</ac:inline-comment-marker><span style="color: rgb(0,204,255);"><ac:inline-comment-marker ac:ref="9426e08f-4642-4544-9c4a-a8164a80c7e5">6</ac:inline-comment-marker><s>3</s></span>.</strong><span style="color: rgb(0,51,102);letter-spacing: 0.0px;"> </span><span style="color: rgb(0,51,102);letter-spacing: 0.0px;">Осуществляется отображение модального окна с текстом &quot;Не удалось подписать документ&quot;, при закрытии которого модальное окно закрывается и осуществляется переход на шаг №<span style="color: rgb(0,204,255);">8</span></span><s style="color: rgb(0,51,102);letter-spacing: 0.0px;"><span style="color: rgb(0,204,255);">4</span></s><span style="color: rgb(0,51,102);letter-spacing: 0.0px;">.</span></p><p style="text-align: left;"><span style="color: rgb(0,204,255);"><strong style="letter-spacing: 0.0px;">Шаг № 7. Информирование пользователя о статусе операции</strong></span></p><p style="margin-left: 40.0px;"><span style="color: rgb(0,204,255);">Если были успешно подписаны все заявки, у которых идентификаторы присутствуют в Массиве_идентификаторов</span></p><ul><li style="list-style-type: none;"><ul><li><span style="letter-spacing: 0.0px;color: rgb(0,204,255);">то осуществляется переход на шаг №8.</span></li><li><span style="color: rgb(0,204,255);">Иначе осуществляется отображение модального окна с текстом &quot;Остались неподписанные документы. Часть документов не была отправлена в банк. Попробуйте повторить операцию позже. Если ошибка не исчезнет, обратитесь в техподдержку по телефону 8 800 100 11 89&quot;. При закрытии модального окна осуществляется переход на шаг №8</span></li></ul></li></ul><p style="text-align: left;"><strong style="letter-spacing: 0.0px;">Шаг №<span style="color: rgb(0,204,255);">8<s>4</s></span>. </strong><span style="letter-spacing: 0.0px;">Завершение процесса.</span></p></td></tr><tr><td colspan="1"><strong style="text-align: left;">Англоязычное наименование (код привилегии):</strong></td><td colspan="1"><span style="color: rgb(0,0,0);">BC.CLIENT.<span style="color: rgb(0,51,102);">CARD.ISSUE.REQUEST.</span>SIGN</span></td></tr></tbody></table><p class="auto-cursor-target"><br /></p></ac:layout-cell></ac:layout-section></ac:layout>'''

        result = filter_all_fragments(html_content)

        print("=" * 80)
        print("ТЕСТ ИЗВЛЕЧЕНИЯ ВСЕХ ФРАГМЕНТОВ:")
        print(f"Результат:")
        print(result)
        print("=" * 80)

    # Запускаем тест
    test_all_fragments()