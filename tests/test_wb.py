from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from conftest import write_xlsx

from unit_economics.columns import ReportFormatError
from unit_economics.operations import ParsedReport
from unit_economics.wb import parse_wb

HEADERS = (
    "Артикул поставщика", "Название", "Тип документа", "Обоснование для оплаты", "Кол-во",
    "Цена розничная с учетом согласованной скидки", "К перечислению Продавцу за реализованный Товар",
    "Услуги по доставке товара покупателю", "Общая сумма штрафов", "Доплаты", "Хранение", "Удержания",
    "Платная приемка", "Дата продажи",
)  # fmt: skip
API_HEADERS = (
    "sa_name", "subject_name", "doc_type_name", "supplier_oper_name", "quantity", "retail_price_withdisc_rub",
    "ppvz_for_pay", "delivery_rub", "penalty", "additional_payment", "storage_fee", "deduction", "acceptance",
    "sale_dt",
)  # fmt: skip
ROWS = (
    ("A-1", "Плед", "Продажа", "Продажа", 2, 1000, 1500, 0, 0, 0, 0, 0, 0, "01.09.2026"),
    ("A-1", "Плед", None, "Логистика", 0, 0, 0, 120, 0, 0, 0, 0, 0, "01.09.2026"),
    ("A-1", "Плед", "Возврат", "Возврат", 1, 1000, 750, 0, 0, 0, 0, 0, 0, "03.09.2026"),
    ("A-1", None, None, "Логистика", 0, 0, 0, 50, 0, 0, 0, 0, 0, "03.09.2026"),
    ("B-2", "Наволочка", "Продажа", "Продажа", 1, 500, 380, 0, 0, 0, 0, 0, 0, "02.09.2026"),
    (None, None, None, "Хранение", 0, 0, 0, 0, 0, 0, 300.5, 0, 0, "07.09.2026"),
    (None, None, None, "Удержание", 0, 0, 0, 0, 0, 0, 0, 1000, 0, "07.09.2026"),
    (None, None, None, "Платная приемка", 0, 0, 0, 0, 0, 0, 0, 0, 200, "07.09.2026"),
    ("A-1", None, "Продажа", "Оплата брака", 1, 0, 900, 0, 0, 0, 0, 0, 0, "05.09.2026"),
    ("B-2", None, "Продажа", "Коррекция продаж", 0, 0, 120, 0, 0, 0, 0, 0, 0, "05.09.2026"),
    ("B-2", None, None, "Штраф", 0, 0, 0, 0, 500, 0, 0, 0, 0, "06.09.2026"),
    ("B-2", None, None, "Доплаты", 0, 0, 0, 0, 0, 75, 0, 0, 0, "06.09.2026"),
    (None,) * 14,  # пустая строка в конце выгрузки
)
FIELDS = ("sold", "returned", "revenue", "commission", "logistics", "other", "payout")


def by_article(report: ParsedReport) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for operation in report.operations:
        entry = result.setdefault(operation.article, dict.fromkeys(FIELDS, 0))
        for field in FIELDS:
            entry[field] += getattr(operation, field)
    return result


def test_returns_reduce_payout_and_quantity_counts(tmp_path: Path) -> None:
    """Возврат уменьшает выплату, продажа двух пледов — две штуки."""
    report = parse_wb(write_xlsx(tmp_path / "wb.xlsx", HEADERS, ROWS))
    articles = by_article(report)
    assert articles["A-1"] == {
        "sold": 2, "returned": 1, "revenue": 100_000, "commission": -25_000, "logistics": -17_000,
        "other": 90_000, "payout": 148_000,
    }  # fmt: skip
    assert articles["B-2"] == {
        "sold": 1, "returned": 0, "revenue": 50_000, "commission": -12_000, "logistics": 0,
        "other": -30_500, "payout": 7_500,
    }  # fmt: skip
    assert articles[""]["payout"] == -150_050  # хранение, удержание, приёмка — общие расходы
    # формула WB: 1500 + 380 + 900 + 120 − 750 − 170 − 500 + 75 − 300,5 − 1000 − 200 = 54,50 ₽
    assert sum(operation.payout for operation in report.operations) == 5_450
    assert report.period == (date(2026, 9, 1), date(2026, 9, 7))
    assert report.rows == 12


def test_unknown_operation_is_reported_not_lost(tmp_path: Path) -> None:
    report = parse_wb(write_xlsx(tmp_path / "wb.xlsx", HEADERS, ROWS))
    assert len(report.problems) == 1
    assert "«Коррекция продаж»" in report.problems[0]
    assert "120,00" in report.problems[0]


def test_api_field_names_give_the_same_result(tmp_path: Path) -> None:
    russian = parse_wb(write_xlsx(tmp_path / "ru.xlsx", HEADERS, ROWS))
    api = parse_wb(write_xlsx(tmp_path / "api.xlsx", API_HEADERS, ROWS))
    assert by_article(api) == by_article(russian)


def test_other_report_is_rejected_with_missing_columns(tmp_path: Path) -> None:
    headers = [header for header in HEADERS if header != "Кол-во"]
    path = write_xlsx(tmp_path / "wb.xlsx", headers, [row[:4] + row[5:] for row in ROWS[:2]])
    with pytest.raises(ReportFormatError, match="«Кол-во»"):
        parse_wb(path)


def test_bad_number_names_the_row(tmp_path: Path) -> None:
    rows = [ROWS[0], ("A-1", "Плед", "Продажа", "Продажа", "два", 1000, 1500, 0, 0, 0, 0, 0, 0, "01.09.2026")]
    with pytest.raises(ReportFormatError, match="строка 3"):
        parse_wb(write_xlsx(tmp_path / "wb.xlsx", HEADERS, rows))


def test_old_xls_and_broken_files_are_explained(tmp_path: Path) -> None:
    with pytest.raises(ReportFormatError, match=r"нужен файл \.xlsx"):
        parse_wb(tmp_path / "отчёт.xls")
    broken = tmp_path / "отчёт.xlsx"
    broken.write_text("это не Excel", encoding="utf-8")
    with pytest.raises(ReportFormatError, match="Не удалось открыть"):
        parse_wb(broken)
