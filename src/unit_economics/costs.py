"""Себестоимость единицы товара: чтение CSV («;» или «,») и XLSX, сохранение в CSV для Excel."""

from __future__ import annotations

import csv
import io
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from unit_economics.columns import Columns, ReportFormatError, read_table, text
from unit_economics.fmt import NBSP, format_amount
from unit_economics.money import MoneyError, is_blank, to_kopecks

ARTICLE = ("Артикул", "Артикул поставщика", "Артикул продавца")
COST = ("Себестоимость", "Себестоимость, руб.", "Себестоимость, ₽", "Себестоимость единицы")


class CostsError(ValueError):
    pass


def _csv_rows(path: Path) -> list[list[str]]:
    try:
        content = path.read_text("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise CostsError(f"Не удалось прочитать {path.name}: {exc}") from exc
    try:
        delimiter = csv.Sniffer().sniff(content[:4096], delimiters=";,\t").delimiter
    except csv.Error:
        delimiter = ";"
    return list(csv.reader(io.StringIO(content), delimiter=delimiter))


def _cell(record: Sequence[object], position: int) -> object:
    return record[position] if position < len(record) else None


def load_costs(path: Path) -> dict[str, int]:
    """Артикул → себестоимость в копейках. Пустая себестоимость — «не задана», а не ноль."""
    records: Sequence[Sequence[object]]
    if path.suffix.lower() == ".xlsx":
        try:
            table = read_table(path, (ARTICLE, COST), "таблицу себестоимости")
        except ReportFormatError as exc:
            raise CostsError(str(exc)) from exc
        columns, records, first_row = table.columns, table.records, table.first_row
    else:
        rows = _csv_rows(path)
        if not rows:
            raise CostsError(f"{path.name}: файл пустой")
        columns, records, first_row = Columns(rows[0]), rows[1:], 2
    article_at, cost_at = columns.find(ARTICLE), columns.find(COST)
    if article_at is None or cost_at is None:
        raise CostsError(f"{path.name}: нужны колонки «Артикул» и «Себестоимость»")
    costs: dict[str, int] = {}
    seen: dict[str, int] = {}
    for offset, record in enumerate(records):
        row = first_row + offset
        article, raw = text(_cell(record, article_at)), _cell(record, cost_at)
        if not article or is_blank(raw):
            continue
        try:
            kopecks = to_kopecks(raw)
        except MoneyError as exc:
            raise CostsError(f"{path.name}, строка {row}: себестоимость {exc}") from exc
        if kopecks < 0:
            raise CostsError(f"{path.name}, строка {row}: себестоимость не может быть отрицательной")
        if article in seen:
            raise CostsError(f"{path.name}: артикул {article} указан дважды — строки {seen[article]} и {row}")
        seen[article] = row
        costs[article] = kopecks
    return costs


def save_costs(path: Path, costs: Mapping[str, int], names: Mapping[str, str] | None = None) -> None:
    """CSV с «;» и запятой в копейках: Excel в русской локали открывает его сразу по колонкам."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Артикул", "Название", "Себестоимость"])
    for article in sorted(costs):
        writer.writerow([article, (names or {}).get(article, ""), format_amount(costs[article]).replace(NBSP, "")])
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(buffer.getvalue(), encoding="utf-8-sig", newline="")
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise CostsError(f"Не удалось сохранить {path.name}: {exc}") from exc
