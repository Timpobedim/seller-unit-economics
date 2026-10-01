"""Отчёт о начислениях Ozon → операции.

Строка — начисление: доставка покупателю, возврат, услуга. Выручка, комиссия и логистика берутся из
своих колонок со знаком, как в отчёте (расходы отрицательные), «Итого» — сумма к выплате по строке.
Всё, что не попало в выручку, комиссию и логистику (эквайринг, услуги, новые колонки Ozon), — «прочее»
= Итого − остальное, поэтому ни одна сумма не теряется.

У Ozon свой формат отчёта и свой разбор — не по правилам WB.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from unit_economics.columns import ReportFormatError, Table, Variants, normalize_header, read_table, text
from unit_economics.fmt import format_rubles
from unit_economics.money import MoneyError, parse_count, to_kopecks
from unit_economics.operations import Operation, ParsedReport, period_of, to_date

PLATFORM = "Ozon"
TYPE = ("Тип начисления",)
REVENUE = ("За продажу или возврат до вычета комиссий и услуг",)
TOTAL = ("Итого", "Итого, руб.", "Сумма итого, руб.")
REQUIRED = (TYPE, REVENUE, TOTAL)
ARTICLE = ("Артикул", "Артикул продавца", "offer_id")
NAME = ("Название товара", "Название товара или услуги")
QUANTITY = ("Количество",)
COMMISSION = ("Комиссия за продажу",)
DATE = ("Дата начисления",)
LOGISTICS = (
    "Сборка заказа",
    "Обработка отправления",
    "Магистраль",
    "Последняя миля",
    "Обратная магистраль",
    "Обработка возврата",
    "Обработка отмененного или невостребованного товара",
    "Обработка невыкупленного товара",
    "Логистика",
    "Обратная логистика",
)
SALES = frozenset({"доставка покупателю"})
RETURNS = frozenset({"получение возврата, отмены, невыкупа от покупателя"})
SERVICES = frozenset(
    normalize_header(name)
    for name in (
        "Оплата эквайринга",
        "Удержание за недовложение товара",
        "Обработка товара в составе грузоместа на FBO",
    )
)


def _position(table: Table, variants: Variants) -> int:
    position = table.columns.find(variants)
    if position is None:  # read_table уже проверил обязательные колонки
        raise ReportFormatError(f"{table.source}: нет колонки «{variants[0]}»")
    return position


def _known(kind: str) -> bool:
    return kind in SALES or kind in RETURNS or kind in SERVICES or kind.startswith("услуга")


def parse_ozon(path: Path) -> ParsedReport:
    table = read_table(path, REQUIRED, "отчёт о начислениях Ozon")
    type_at, revenue_at, total_at = (_position(table, variants) for variants in REQUIRED)
    article_at, name_at, quantity_at, commission_at, date_at = (
        table.columns.find(variants) for variants in (ARTICLE, NAME, QUANTITY, COMMISSION, DATE)
    )
    logistics_at = table.columns.find_all(LOGISTICS)
    operations: list[Operation] = []
    unknown: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])  # тип → [строк, итого]
    dates = []
    for offset, record in enumerate(table.records):
        operation = text(record[type_at])
        if not operation:
            continue  # строка «Итого» внизу отчёта и пустые строки
        kind = normalize_header(operation)
        try:
            quantity = abs(parse_count(record[quantity_at])) if quantity_at is not None else 1
            revenue = to_kopecks(record[revenue_at])
            commission = to_kopecks(record[commission_at]) if commission_at is not None else 0
            logistics = sum(to_kopecks(record[position]) for position in logistics_at)
            total = to_kopecks(record[total_at])
        except MoneyError as exc:
            raise ReportFormatError(f"{table.source}, строка {table.first_row + offset}: {exc}") from exc
        if not _known(kind):
            unknown[operation][0] += 1
            unknown[operation][1] += total
        operations.append(
            Operation(
                platform=PLATFORM,
                article=text(record[article_at]) if article_at is not None else "",
                name=text(record[name_at]) if name_at is not None else "",
                operation=operation,
                sold=quantity if kind in SALES else 0,
                returned=quantity if kind in RETURNS else 0,
                revenue=revenue,
                commission=commission,
                logistics=logistics,
                other=total - revenue - commission - logistics,
            )
        )
        if date_at is not None:
            dates.append(to_date(record[date_at]))
    problems = [
        f"{table.source}: неизвестный «Тип начисления» «{name}» — строк: {rows}, итого {format_rubles(amount)}; "
        "учтено в прочем"
        for name, (rows, amount) in unknown.items()
    ]
    if quantity_at is None:
        problems.append(f"{table.source}: нет колонки «Количество» — каждая продажа и возврат считаются за 1 шт.")
    return ParsedReport(PLATFORM, table.source, tuple(operations), tuple(problems), period_of(dates), len(operations))
