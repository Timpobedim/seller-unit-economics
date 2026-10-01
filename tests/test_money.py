from __future__ import annotations

from decimal import Decimal

import pytest

from unit_economics.fmt import format_count, format_percent, format_rubles, format_value, plural
from unit_economics.money import MoneyError, parse_count, to_kopecks
from unit_economics.pnl import FILES

NBSP = "\u00a0"


@pytest.mark.parametrize(
    ("value", "kopecks"),
    [
        (1500, 150_000),
        (1500.5, 150_050),
        ("1500,50", 150_050),  # int("1500,50") здесь упал бы
        ("1 500,50", 150_050),
        (f"1{NBSP}500,50", 150_050),
        ("−2 000 ₽", -200_000),
        ("1.500,50", 150_050),
        ("1,500.50", 150_050),
        ("2000руб.", 200_000),
        ("0,005", 1),
        (Decimal("12.345"), 1235),
        (None, 0),
        (float("nan"), 0),
        ("", 0),
        ("  ", 0),
    ],
)
def test_amounts_from_cells_and_inputs(value: object, kopecks: int) -> None:
    assert to_kopecks(value) == kopecks


@pytest.mark.parametrize("value", ["abc", "NaN", "Infinity", "1,2,3", "12 руб 50", True])
def test_garbage_is_an_error_not_a_crash(value: object) -> None:
    with pytest.raises(MoneyError, match="не число"):
        to_kopecks(value)


def test_counts() -> None:
    assert [parse_count(value) for value in (2, "2", 2.0, None)] == [2, 2, 2, 0]
    with pytest.raises(MoneyError, match="не целое"):
        parse_count("1,5")


def test_russian_number_formatting() -> None:
    assert format_rubles(123_456_789) == f"1{NBSP}234{NBSP}567,89{NBSP}₽"
    assert format_rubles(-5) == f"−0,05{NBSP}₽"
    assert format_count(-1234) == f"−1{NBSP}234"
    assert format_percent(0.1234) == f"12,3{NBSP}%"
    assert format_percent(-0.05) == f"−5,0{NBSP}%"
    assert format_value(None, "money") == "—"
    assert [plural(count, FILES) for count in (1, 3, 5, 11, 21)] == ["файл", "файла", "файлов", "файлов", "файл"]
