# app/logging_config.py

import logging
import sys

# Для logger.info() — не обрезает (пропускает как есть).
# # Для logger.debug() — не выводит ничего (если уровень INFO).
# # Для уровня DEBUG — обрезает logger.debug() до 500 символов.
class TrimFilter(logging.Filter):
    def __init__(self, logger_level):
        super().__init__()
        self.logger_level = logger_level

    def filter(self, record):
        if record.levelno == logging.DEBUG:
            if isinstance(record.msg, str) and len(record.msg) > 500:
                record.msg = record.msg[:500] + "..."
            return self.logger_level <= logging.DEBUG  # False, если логгер INFO
        return True

def setup_logging():
    logger = logging.getLogger()
    # Здесь можно добавить другие настройки (форматирование, обработчики и т.д.)
    logging.basicConfig(
        level=logging.DEBUG,  # Уровень логов (DEBUG и выше, включая ERROR)
        format='%(asctime)s [%(levelname)s] %(filename)s: %(message)s',
        handlers=[
            logging.StreamHandler(),  # Вывод в консоль
            logging.FileHandler('analyze_pages.log', encoding='utf-8')  # Вывод в файл с UTF-8
        ]
    )
    logger.addFilter(TrimFilter(logger.level))

    # Установка кодировки UTF-8 для консоли на Windows
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding='utf-8')

    logger.setLevel(logging.DEBUG)