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
    logger.debug("[filter_all_fragments] <- {%s}", html)

    extractor = create_all_fragments_extractor()
    result = extractor.extract(html)

    logger.info("[filter_all_fragments] -> {%s}", result)
    return result


def test_filter_all_fragments():
    """Тестовый метод для проверки работы filter_all_fragments()"""

    # МЕСТО ДЛЯ ВСТАВКИ HTML ФРАГМЕНТА
    html_fragment = '''
<p class="auto-cursor-target"><br /></p><table class="relative-table wrapped" style="width: 65.2473%;"><colgroup class=""><col class="" style="width: 7.68943%;" /><col class="" style="width: 36.8671%;" /><col class="" style="width: 108.705%;" /></colgroup><thead class=""><tr class=""><th><p>Шаг №</p></th><th><p>Название шага</p></th><th><p>Описание шага</p></th></tr></thead><tbody class=""><tr class=""><td class="highlight-grey" data-highlight-colour="grey">1.1</td><td><p><strong>название 1</strong></p></td><td><p><span style="color: rgb(0,51,102);">Описание&nbsp; 1</span></p></td></tr><tr class=""><td class="highlight-grey" data-highlight-colour="grey">1.2</td><td><p><strong>название 2</strong></p></td><td><p>Опиасние 2</p></td></tr></tbody></table><p class="auto-cursor-target"><br /></p>            
'''

    print("=== ВХОДНОЙ HTML ===")
    print(html_fragment)
    print("\n=== РЕЗУЛЬТАТ ОБРАБОТКИ ===")

    result = filter_all_fragments(html_fragment)

    print(f"'{result}'")
    print("\n=== КОНЕЦ ===")


if __name__ == "__main__":
    test_filter_all_fragments()