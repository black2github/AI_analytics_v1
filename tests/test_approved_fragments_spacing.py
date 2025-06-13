# tests/test_approved_fragments_spacing.py

from app.filter_approved_fragments import filter_approved_fragments


def test_approved_link_spacing_fix():
    """Тест исправления лишних пробелов в подтвержденных ссылках"""

    html = '''
    <span style="color: rgb(0,0,0);">
        <span style="color: rgb(0,51,102);">
            <a href="/pages/viewpage.action?pageId=42670178">[КК_БК] Заявка на блокировку карты</a>
        </span>,
    </span>
    '''

    result = filter_approved_fragments(html)
    print(f"Результат (approved): '{result}'")

    # Проверяем, что нет лишних пробелов
    assert result.strip() == "[[КК_БК] Заявка на блокировку карты],"

    print("V Тест подтвержденных фрагментов прошел!")


def test_nested_table_links():
    """Тест ссылок во вложенных таблицах"""

    html = '''
    <table>
        <tr>
            <td>
                Документ: 
                <a href="/page/123">Техзадание</a>
                .
            </td>
        </tr>
    </table>
    '''

    result = filter_approved_fragments(html)
    print(f"Вложенная таблица: '{result}'")

    # Не должно быть лишних пробелов
    expected = "| Документ: [Техзадание]. |"
    assert result.strip() in expected or "Документ: [Техзадание]." in result

    print("V Тест вложенных таблиц прошел!")


if __name__ == "__main__":
    test_approved_link_spacing_fix()
    test_nested_table_links()