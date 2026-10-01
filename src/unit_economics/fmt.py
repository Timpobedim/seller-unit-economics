"""Числа по-русски: «1 234 567,89 ₽», «12,5 %», неразрывные пробелы, прочерк вместо пустоты."""

from __future__ import annotations

from typing import Literal

Kind = Literal["money", "count", "percent", "text"]
Value = int | float | str | None
NBSP = "\u00a0"


def plural(count: int, forms: tuple[str, str, str]) -> str:
    """1 файл, 2 файла, 5 файлов."""
    if count % 10 == 1 and count % 100 != 11:
        return forms[0]
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return forms[1]
    return forms[2]


def format_count(value: int) -> str:
    return f"{value:,}".replace(",", NBSP).replace("-", "−")


def format_amount(kopecks: int) -> str:
    """Сумма без знака рубля — для полей ввода: «1 350,00»."""
    sign = "−" if kopecks < 0 else ""
    whole, fraction = divmod(abs(kopecks), 100)
    return f"{sign}{format_count(whole)},{fraction:02d}"


def format_rubles(kopecks: int) -> str:
    return f"{format_amount(kopecks)}{NBSP}₽"


def format_percent(value: float) -> str:
    return f"{value * 100:.1f}".replace(".", ",").replace("-", "−") + f"{NBSP}%"


def format_value(value: Value, kind: Kind) -> str:
    if value is None:
        return "—"
    if kind == "money":
        return format_rubles(int(value))
    if kind == "count":
        return format_count(int(value))
    if kind == "percent":
        return format_percent(float(value))
    return str(value)
