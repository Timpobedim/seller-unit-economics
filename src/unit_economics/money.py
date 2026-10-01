"""Суммы из отчётов и полей ввода → копейки. Целые копейки дают точную арифметику без float.

Ввод вида «1500,50» или «1 500,50 ₽» разбирается, а не роняет приложение, как сделал бы int().
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

KOPECK = Decimal("0.01")
_SPACES = re.compile(r"[\s\u00a0\u202f']")
_CURRENCY = re.compile(r"(₽|руб\.?|р\.)$", re.IGNORECASE)
_MINUS = str.maketrans({"−": "-", "–": "-", "—": "-"})


class MoneyError(ValueError):
    pass


def is_blank(value: object) -> bool:
    return (
        value is None
        or (isinstance(value, float) and math.isnan(value))
        or (isinstance(value, str) and not value.strip())
    )


def parse_decimal(value: object) -> Decimal:
    """Число из ячейки или поля ввода: 1500, 1500.5, «1 500,50», «−2 000 ₽», «1.500,50». Пусто → 0."""
    if is_blank(value):
        return Decimal(0)
    if isinstance(value, bool):
        raise MoneyError(f"«{value}» — не число")
    if isinstance(value, int | Decimal):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(repr(value))
    else:
        text = _CURRENCY.sub("", _SPACES.sub("", str(value)).translate(_MINUS))
        if "," in text and "." in text:  # десятичный разделитель — тот, что правее
            text = (
                text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
            )
        elif text.count(",") == 1:
            text = text.replace(",", ".")
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise MoneyError(f"«{value}» — не число") from exc
    if not number.is_finite():
        raise MoneyError(f"«{value}» — не число")
    return number


def to_kopecks(value: object) -> int:
    return int(parse_decimal(value).quantize(KOPECK, ROUND_HALF_UP) * 100)


def parse_count(value: object) -> int:
    number = parse_decimal(value)
    if number != number.to_integral_value():
        raise MoneyError(f"«{value}» — не целое число")
    return int(number)
