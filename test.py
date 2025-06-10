import logging
logging.basicConfig(level=logging.DEBUG)
from app.filter_approved_fragments import filter_approved_fragments

import logging
import sys

def setup_logging():
    # Настройка логирования
    logging.basicConfig(
        level=logging.DEBUG,  # Уровень логов (DEBUG и выше, включая ERROR)
        format='%(asctime)s [%(levelname)s] %(filename)s: %(message)s',
        handlers=[
            logging.StreamHandler(),  # Вывод в консоль
            logging.FileHandler('analyze_pages.log', encoding='utf-8')  # Вывод в файл с UTF-8
        ]
    )

    # Установка кодировки UTF-8 для консоли на Windows
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding='utf-8')


setup_logging()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    with open("test.html", "r", encoding="utf-8") as f:
        html = f.read()

    result = filter_approved_fragments(html)
    print("РЕЗУЛЬТАТ:")
    print("=" * 50)
    print(result)
    print("=" * 50)
    print(f"Длина результата: {len(result)} символов")