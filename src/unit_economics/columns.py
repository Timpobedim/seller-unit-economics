"""Таблица из Excel-отчёта: поиск строки заголовков и колонок по названиям.

Кабинеты маркетплейсов меняют порядок колонок и добавляют новые, а у Ozon над заголовками бывают
строки с названием отчёта и периодом. Поэтому колонки ищутся по названию (регистр, «ё» и лишние
пробелы не важны), а строка заголовков — среди первых 30 строк каждого листа.
"""

from __future__ import annotations

import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException

from unit_economics.money import is_blank

Variants = Sequence[str]
HEADER_SEARCH_ROWS = 30


class ReportFormatError(ValueError):
    """Файл не похож на ожидаемый отчёт; текст — для пользователя."""


def normalize_header(value: object) -> str:
    return " ".join(str(value).replace("ё", "е").replace("Ё", "Е").lower().split())


def text(value: object) -> str:
    """Ячейка как текст: пусто для NaN и None, 12345.0 → «12345» (числовые артикулы)."""
    if is_blank(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


class Columns:
    """Позиции колонок по названиям; вариант — точное название или (prefix=True) его начало."""

    def __init__(self, headers: Sequence[object]) -> None:
        self._positions: dict[str, int] = {}
        for position, header in enumerate(headers):
            key = normalize_header(text(header))
            if key and key not in self._positions:
                self._positions[key] = position

    def find(self, variants: Variants, *, prefix: bool = False) -> int | None:
        for variant in variants:
            position = self._positions.get(normalize_header(variant))
            if position is not None:
                return position
        if prefix:
            for variant in variants:
                key = normalize_header(variant)
                for normalized, position in self._positions.items():
                    if normalized.startswith(key):
                        return position
        return None

    def find_all(self, variants: Variants) -> list[int]:
        """Все колонки, чьё название начинается с одного из вариантов, — без повторов."""
        keys = [normalize_header(variant) for variant in variants]
        return [
            position
            for normalized, position in self._positions.items()
            if any(normalized == key or normalized.startswith(key + " ") for key in keys)
        ]


@dataclass(frozen=True)
class Table:
    records: list[tuple[object, ...]]
    columns: Columns
    first_row: int  # номер строки Excel с первой записью — для сообщений об ошибках
    source: str


def read_table(path: Path, required: Sequence[Variants], what: str) -> Table:
    if path.suffix.lower() != ".xlsx":
        raise ReportFormatError(f"{path.name}: нужен файл .xlsx — откройте отчёт в Excel и сохраните как «Книга Excel»")
    try:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object, engine="openpyxl")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, InvalidFileException) as exc:
        raise ReportFormatError(f"Не удалось открыть {path.name}: {exc}") from exc
    closest: list[str] = [variants[0] for variants in required]
    for raw in sheets.values():
        for index in range(min(HEADER_SEARCH_ROWS, len(raw))):
            columns = Columns(list(raw.iloc[index]))
            missing = [variants[0] for variants in required if columns.find(variants) is None]
            if not missing:
                records = list(raw.iloc[index + 1 :].itertuples(index=False, name=None))
                return Table(records, columns, first_row=index + 2, source=path.name)
            if len(missing) < len(closest):
                closest = missing
    names = ", ".join(f"«{name}»" for name in closest)
    raise ReportFormatError(f"{path.name}: не похоже на {what} — не нашлись колонки {names}")
