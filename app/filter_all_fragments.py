# app/filter_all_fragments.py

import logging
from app.content_extractor import create_all_fragments_extractor

logger = logging.getLogger(__name__)


def filter_all_fragments(html: str) -> str:
    """
    Извлекает все фрагменты из HTML возвращая их с гибридной разметкой (Markdown + HTML)
    без учета цвета элементов
    """
    logger.info("[filter_all_fragments] <- {%s}", html[:200] + "...")

    extractor = create_all_fragments_extractor()
    result = extractor.extract(html)

    logger.info("[filter_all_fragments] -> {%s}", result)
    return result


def test_filter_all_fragments():
    """Тестовый метод для проверки работы filter_all_fragments()"""

    # МЕСТО ДЛЯ ВСТАВКИ HTML ФРАГМЕНТА
    html_fragment = '''
    <h1 id="id-[КК_Карты]Настройкаскроллера&quot;Списоккарт&quot;-Связанныеатрибуты"><span style="color: rgb(23,43,77);">Связанные атрибуты</span></h1><p><span style="color: rgb(23,43,77);">Версия структуры скроллера = 1</span></p><p><span style="color: rgb(23,43,77);">Идентификатор скроллера = "cc_card_list"</span></p>
            '''

    print("=== ВХОДНОЙ HTML ===")
    print(html_fragment)
    print("\n=== РЕЗУЛЬТАТ ОБРАБОТКИ ===")

    result = filter_all_fragments(html_fragment)

    print(f"'{result}'")
    print("\n=== КОНЕЦ ===")


if __name__ == "__main__":
    test_filter_all_fragments()