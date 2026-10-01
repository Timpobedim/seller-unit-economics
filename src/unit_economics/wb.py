"""Детализация еженедельного отчёта Wildberries → операции.

Сумма к оплате у WB складывается так: «К перечислению» за продажи и компенсации − «К перечислению»
за возвраты − логистика − штрафы + доплаты − хранение − удержания − платная приёмка. Денежные колонки
учитываются в каждой строке, а «К перечислению» — по «Обоснованию для оплаты».

Строки «Возврат» уменьшают выплату, а продажа считается по «Кол-во», а не за одну штуку.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from unit_economics.columns import ReportFormatError, Table, Variants, normalize_header, read_table, text
from unit_economics.fmt import format_rubles
from unit_economics.money import MoneyError, parse_count, to_kopecks
from unit_economics.operations import Operation, ParsedReport, period_of, to_date

PLATFORM = "WB"
ARTICLE = ("Артикул поставщика", "Артикул продавца", "sa_name")
OPERATION = ("Обоснование для оплаты", "supplier_oper_name")
QUANTITY = ("Кол-во", "Количество", "quantity")
PRICE = ("Цена розничная с учетом согласованной скидки", "retail_price_withdisc_rub")
FOR_PAY = ("К перечислению Продавцу за реализованный Товар", "ppvz_for_pay")
REQUIRED = (ARTICLE, OPERATION, QUANTITY, PRICE, FOR_PAY)
NAME = ("Название", "Предмет", "subject_name")
DOC_TYPE = ("Тип документа", "doc_type_name")
DATE = ("Дата продажи", "sale_dt", "Дата операции", "rr_dt")
# денежная колонка → куда относится и с каким знаком для продавца
MONEY_COLUMNS: tuple[tuple[Variants, str, int], ...] = (
    (("Услуги по доставке товара покупателю", "delivery_rub"), "logistics", -1),
    (
        (
            "Возмещение издержек по перевозке/по складским операциям с товаром",
            "Возмещение издержек по перевозке",
            "rebill_logistic_cost",
        ),
        "logistics",
        -1,
    ),
    (("Общая сумма штрафов", "Штрафы", "penalty"), "other", -1),
    (("Доплаты", "additional_payment"), "other", 1),
    (("Хранение", "storage_fee"), "other", -1),
    (("Удержания", "deduction"), "other", -1),
    (("Платная приемка", "acceptance"), "other", -1),
)
SALE, RETURN = "продажа", "возврат"
COMPENSATIONS = frozenset(
    normalize_header(name)
    for name in (
        "Оплата брака",
        "Оплата потерянного товара",
        "Компенсация подмененного товара",
        "Компенсация ущерба",
        "Добровольная компенсация при возврате",
        "Частичная компенсация брака",
        "Компенсация брака",
        "Авансовая оплата за товар без движения",
    )
)
SERVICES = frozenset(
    normalize_header(name)
    for name in (
        "Логистика",
        "Коррекция логистики",
        "Логистика сторно",
        "Хранение",
        "Штраф",
        "Штрафы",
        "Доплаты",
        "Удержание",
        "Удержания",
        "Платная приемка",
        "Возмещение издержек по перевозке",
        "Возмещение издержек по перевозке/по складским операциям с товаром",
        "Возмещение за выдачу и возврат товаров на ПВЗ",
    )
)


def _position(table: Table, variants: Variants) -> int:
    position = table.columns.find(variants)
    if position is None:  # read_table уже проверил обязательные колонки
        raise ReportFormatError(f"{table.source}: нет колонки «{variants[0]}»")
    return position


def parse_wb(path: Path) -> ParsedReport:
    table = read_table(path, REQUIRED, "детализацию еженедельного отчёта WB")
    article_at, operation_at, quantity_at, price_at, pay_at = (_position(table, variants) for variants in REQUIRED)
    name_at, doc_at, date_at = (table.columns.find(variants) for variants in (NAME, DOC_TYPE, DATE))
    money = [
        (position, bucket, sign)
        for variants, bucket, sign in MONEY_COLUMNS
        if (position := table.columns.find(variants)) is not None
    ]
    operations: list[Operation] = []
    unknown: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])  # обоснование → [строк, к перечислению]
    orphans = 0
    dates = []
    for offset, record in enumerate(table.records):
        operation = text(record[operation_at])
        if not operation:
            continue  # пустая строка или строка итогов
        kind = normalize_header(operation)
        doc = normalize_header(text(record[doc_at])) if doc_at is not None else ""
        article = text(record[article_at])
        sold = returned = revenue = commission = 0
        buckets = {"logistics": 0, "other": 0}
        try:
            quantity = parse_count(record[quantity_at])
            price = to_kopecks(record[price_at])
            for_pay = to_kopecks(record[pay_at])
            if kind == SALE:
                sold, revenue = quantity, price * quantity
                commission = for_pay - revenue
            elif kind == RETURN:
                returned, revenue = quantity, -price * quantity
                commission = price * quantity - for_pay  # вместе с выручкой возвращается и комиссия с неё
            else:
                signed = -for_pay if doc == RETURN else for_pay
                buckets["other"] += signed
                if kind not in COMPENSATIONS and kind not in SERVICES:
                    unknown[operation][0] += 1
                    unknown[operation][1] += signed
            for position, bucket, sign in money:
                buckets[bucket] += sign * to_kopecks(record[position])
        except MoneyError as exc:
            raise ReportFormatError(f"{table.source}, строка {table.first_row + offset}: {exc}") from exc
        if kind in (SALE, RETURN) and not article:
            orphans += 1
        name = text(record[name_at]) if name_at is not None else ""
        operations.append(
            Operation(
                PLATFORM,
                article,
                name,
                operation,
                sold,
                returned,
                revenue,
                commission,
                buckets["logistics"],
                buckets["other"],
            )
        )
        if date_at is not None:
            dates.append(to_date(record[date_at]))
    problems = [
        f"{table.source}: неизвестное «Обоснование для оплаты» «{name}» — строк: {rows}, "
        f"к перечислению {format_rubles(amount)}; учтено в прочих удержаниях и доплатах"
        for name, (rows, amount) in unknown.items()
    ]
    if orphans:
        problems.append(f"{table.source}: продаж и возвратов без артикула — {orphans}; отнесены к общим расходам")
    return ParsedReport(PLATFORM, table.source, tuple(operations), tuple(problems), period_of(dates), len(operations))
