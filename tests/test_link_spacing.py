# tests/test_link_spacing.py

from app.filter_all_fragments import filter_all_fragments


def test_link_spacing_fix():
    """Тест исправления лишних пробелов в ссылках"""

    html = '''
    <span style="color: rgb(0,0,0);">
        <span style="color: rgb(0,51,102);">
            <a href="/pages/viewpage.action?pageId=42670178">[КК_БК] Заявка на блокировку карты</a>
        </span>,
    </span>
    '''

    result = filter_all_fragments(html)
    print(f"Результат: '{result}'")

    # Проверяем, что нет лишних пробелов
    assert result.strip() == "[[КК_БК] Заявка на блокировку карты],"
    # Не должно быть: "- [[КК_БК] Заявка на блокировку карты] ,"

    print("V Тест прошел! Лишние пробелы убраны.")


def test_complex_link_structure():
    """Тест сложной структуры с вложенными span и ссылками"""

    html = '''
    <p>
        Смотри документ: 
        <span style="color: rgb(0,0,0);">
            <span style="color: rgb(0,51,102);">
                <a href="/pages/viewpage.action?pageId=12345">Требования к системе</a>
            </span>
            и еще 
            <span style="color: rgb(255,0,0);">
                <a href="/pages/viewpage.action?pageId=67890">Техническое задание</a>
            </span>.
        </span>
    </p>
    '''

    result = filter_all_fragments(html)
    print(f"Сложная структура: '{result}'")

    # Ожидаем правильный результат без лишних пробелов
    expected = "Смотри документ: [Требования к системе] и еще [Техническое задание]."
    assert result.strip() == expected

    print("V Сложная структура обработана корректно!")


if __name__ == "__main__":
    test_link_spacing_fix()
    test_complex_link_structure()
