# app/style_utils.py

import re
from bs4 import Tag


def has_colored_style(element: Tag) -> bool:
    """Проверяет, имеет ли элемент цветной стиль"""
    if not isinstance(element, Tag):
        return False

    style = element.get("style", "").lower()
    if not style or "color" not in style:
        return False

    color_match = re.search(r'color\s*:\s*([^;]+)', style)
    if not color_match:
        return False

    color_value = color_match.group(1).strip()
    return not _is_black_color(color_value)


def _is_black_color(color_value: str) -> bool:
    """Проверяет, является ли цвет черным"""
    color_value = color_value.strip().lower()
    black_colors = {
        'black', '#000', '#000000',
        'rgb(0,0,0)', 'rgb(0, 0, 0)',
        'rgba(0,0,0,1)', 'rgba(0, 0, 0, 1)',
        'rgb(51,51,0)', 'rgb(51, 51, 0)',
        'rgb(0,51,0)', 'rgb(0, 51, 0)',
        'rgb(0,51,102)', 'rgb(0, 51, 102)',
        'rgb(51,51,51)', 'rgb(51, 51, 51)',
        'rgb(23,43,77)', 'rgb(23, 43, 77)'
    }
    return color_value in black_colors