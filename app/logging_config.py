# app/logging_config.py

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