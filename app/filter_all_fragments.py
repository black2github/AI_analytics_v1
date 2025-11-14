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
<h1 class="auto-cursor-target">header_1</h1><table class="wrapped"><tbody><tr><td class="highlight-grey" title="Цвет фона: " data-highlight-colour="grey"><strong title="">hdr1</strong></td><td><h2>header_2</h2></td></tr><tr><td class="highlight-grey" title="Цвет фона: " data-highlight-colour="grey"><strong title="">hdr2&nbsp;</strong></td><td><div class="content-wrapper"><p class="auto-cursor-target">Происходит поиск записи <ac:link><ri:page ri:content-title="Филиал и подразделение Банка" /></ac:link>&nbsp;для которой выполнено: <ac:link><ri:page ri:content-title="Филиал и подразделение Банка" /></ac:link><span>.&lt;</span><span>Код подразделения</span><span>&gt; == {Код подразделения}.</span></p><p class="auto-cursor-target"><br /></p><table class="wrapped" data-mce-resize="false"><tbody><tr><th colspan="2" scope="colgroup">hdr21</th><th scope="col">hdr22</th></tr><tr><td colspan="2"><strong>Шаг 111</strong><br /><strong><br /></strong></td><td><h3>header_3</h3><p>just text</p></td></tr><tr><td colspan="2"><p><strong>Шаг 4</strong></p></td><td><p><strong>(Инициализация реквизитов клиента)</strong></p><p>Происходит поиск записи <a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=328259" rel="nofollow">Клиент Банка</a> для которой выполнено <a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=328259" rel="nofollow">Клиент Банка</a><span>.&lt;GUID клиента в ЕСК</span><span>&gt; == {Идентификатор клиента</span><span>}</span></p><p><strong>Если </strong>з<span>апись не найдена </span><span><strong>ИЛИ</strong> </span><a href="https://confluence.gboteam.ru/pages/viewpage.action?pageId=328259" rel="nofollow">Клиент Банка</a><span>.&lt;</span><span style="color: rgb(23,43,77);">ИНН/КИО</span><span>&gt; != {ИНН клиента}, </span><span><strong>то </strong>происходит:</span></p><ol><li><span>журналирование</span></li><li><span>переход на Шаг №9</span></li></ol><p><strong>Иначе</strong></p><ol><li><span>С использованием найденной записи происходит инициализация атрибутов:&nbsp;</span></li></ol><table class="wrapped" data-mce-resize="false"><tbody><tr><th>hdr221</th><th>hdr222</th></tr><tr><td>текст1</td><td><p class="auto-cursor-target">текст2</p><table class="wrapped" data-mce-resize="false"><colgroup><col /><col /></colgroup><tbody><tr><th scope="col">Шаги</th><th scope="col"><span style="color: rgb(255,102,0);">Описание</span></th></tr><tr><td>hdr222.1</td><td><span style="color: rgb(255,102,0);">hdr222.2</span></td></tr><tr><td>hdr222.3</td><td><span style="color: rgb(255,102,0);">hdr222.4</span></td></tr></tbody></table><p class="auto-cursor-target"><span style="color: rgb(255,102,0);">текст3</span></p></td></tr></tbody></table><p class="auto-cursor-target"><br /></p></td></tr></tbody></table><p class="auto-cursor-target"><br /></p></div></td></tr></tbody></table><p class="auto-cursor-target"><br /></p><p class="auto-cursor-target"><br /></p>            
'''

    print("=== ВХОДНОЙ HTML ===")
    print(html_fragment)
    print("\n=== РЕЗУЛЬТАТ ОБРАБОТКИ ===")

    result = filter_all_fragments(html_fragment)

    print(f"'{result}'")
    print("\n=== КОНЕЦ ===")


if __name__ == "__main__":
    test_filter_all_fragments()