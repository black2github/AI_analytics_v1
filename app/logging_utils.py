# app/logging_utils.py

import logging


def set_log_level(level_name: str):
    """
    Динамически изменяет уровень логирования.

    Args:
        level_name: Уровень логирования ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
    """
    level = getattr(logging, level_name.upper(), logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(level)

    # Обновляем уровень для всех обработчиков
    for handler in logger.handlers:
        handler.setLevel(level)

        # Обновляем фильтр, если это наш TrimFilter
        for filter_obj in handler.filters:
            if hasattr(filter_obj, 'logger_level'):
                filter_obj.logger_level = level

    logging.info(f"Log level changed to: {level_name.upper()}")


def get_current_log_level() -> str:
    """Возвращает текущий уровень логирования."""
    logger = logging.getLogger()
    return logging.getLevelName(logger.level)


def log_sample_messages():
    """Выводит примеры сообщений разных уровней для тестирования."""
    logger = logging.getLogger(__name__)

    # Генерируем длинное сообщение для тестирования обрезки
    long_message = "A" * 1200  # 1200 символов

    logger.debug("DEBUG: Это отладочное сообщение (должно быть скрыто)")
    logger.info(f"INFO: Короткое информационное сообщение")
    logger.info(f"INFO: Длинное информационное сообщение: {long_message}")
    logger.warning("WARNING: Предупреждение")
    logger.error("ERROR: Ошибка")