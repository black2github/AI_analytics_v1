# app/logging_config.py

import logging
import sys


class TrimFilter(logging.Filter):
    """
    Фильтр для обрезки длинных сообщений и установки уровня логирования.
    - DEBUG записи полностью исключаются
    - INFO записи обрезаются до 1000 символов
    - WARNING и выше пропускаются без изменений
    """

    def __init__(self, logger_level=logging.INFO):
        super().__init__()
        self.logger_level = logger_level

    def filter(self, record):
        # Исключаем DEBUG записи
        if record.levelno == logging.DEBUG:
            return False  # DEBUG записи не попадают в журнал

        # Обрезаем INFO записи до 1000 символов
        if record.levelno == logging.INFO:
            if isinstance(record.msg, str) and len(record.msg) > 1000:
                record.msg = record.msg[:1000] + "... [обрезано]"
            # Также обрабатываем случай с аргументами
            if hasattr(record, 'args') and record.args:
                try:
                    # Форматируем сообщение с аргументами
                    formatted_msg = record.msg % record.args
                    if len(formatted_msg) > 1000:
                        record.msg = formatted_msg[:1000] + "... [обрезано]"
                        record.args = ()  # Очищаем args, так как уже отформатировали
                except (TypeError, ValueError):
                    # Если форматирование не удалось, обрезаем только msg
                    if len(str(record.msg)) > 1000:
                        record.msg = str(record.msg)[:1000] + "... [обрезано]"
            return True

        # WARNING, ERROR, CRITICAL пропускаем без изменений
        return True


def setup_logging():
    """
    Настройка логирования с уровнем INFO и обрезкой длинных сообщений.
    """
    logger = logging.getLogger()

    # Устанавливаем уровень INFO (DEBUG исключается)
    logger.setLevel(logging.INFO)

    # Очищаем существующие обработчики
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Настраиваем формат логирования
    formatter = logging.Formatter(
        '%(asctime)s,%(msecs)03d [%(levelname)s] %(filename)s:%(lineno)d %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Консольный обработчик
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Файловый обработчик
    file_handler = logging.FileHandler('requirements_analyzer.log', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    # Добавляем фильтр обрезки к обоим обработчикам
    trim_filter = TrimFilter(logging.INFO)
    console_handler.addFilter(trim_filter)
    file_handler.addFilter(trim_filter)

    # Добавляем обработчики к логгеру
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    # Установка кодировки UTF-8 для консоли на Windows
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            # Для старых версий Python
            pass

    # Настройка логирования для внешних библиотек
    # Снижаем уровень логирования для шумных библиотек
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('chromadb').setLevel(logging.WARNING)
    logging.getLogger('langchain').setLevel(logging.WARNING)
    logging.getLogger('openai').setLevel(logging.WARNING)

    logger.info("Logging configured: level=INFO, max_message_length=1000 chars")