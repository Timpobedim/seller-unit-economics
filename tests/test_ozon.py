from __future__ import annotations

from pathlib import Path

import pytest
from conftest import write_xlsx

from unit_economics.columns import ReportFormatError
from unit_economics.ozon import parse_ozon

HEADERS = (
    "Дата начисления", "Тип начисления", "Номер отправления или идентификатор услуги", "SKU", "Артикул",
    "Название товара или услуги", "Количество", "За продажу или возврат до вычета комиссий и услуг",
    "Ставка комиссии", "Комиссия за продажу",
    "Обработка отправления (Drop-off/Pick-up) (разбивается по товарам пропорционально количеству в отправлении)",
    "Последняя миля (разбивается по товарам пропорционально доле цены товара в сумме отправления)",
    "Логистика", "Обратная логистика", "Обработка возврата", "Итого",
)  # fmt: skip
TITLE = (("Отчёт о начислениях",), ("Период: 01.08.2026 – 31.08.2026",), ())
RETURN = "Получение возврата, отмены, невыкупа от покупателя"
ROWS = (
    ("05.08.2026", "Доставка покупателю", "123-1", 111, "A-1", "Плед", 2, 4000, 17, -680, -20, -220, -120, 0, 0, 2960),
    ("06.08.2026", "Оплата эквайринга", "123-1", 111, "A-1", "Плед", 0, 0, 0, 0, 0, 0, 0, 0, 0, -60),
    ("10.08.2026", RETURN, "123-2", 111, "A-1", "Плед", 1, -2000, 17, 340, 0, 0, 0, -60, -25, -1745),
    ("31.08.2026", "Услуга размещения товаров на складе", "s-1", None, None, None, None, 0, None, 0, 0, 0, 0, 0, 0,
     -1850.4),
    ("31.08.2026", "Корректировка стоимости услуги", "s-2", None, None, None, None, 0, None, 0, 0, 0, 0, 0, 0, 120),
    ("Итого", None, None, None, None, None, None, 2000, None, -340, -20, -220, -120, -60, -25, -575.4),
)  # fmt: skip


def test_title_rows_and_totals_row_are_handled(tmp_path: Path) -> None:
    report = parse_ozon(write_xlsx(tmp_path / "ozon.xlsx", HEADERS, ROWS, TITLE))
    assert report.rows == 5  # строка «Итого» внизу не посчитана второй раз
    goods = [operation for operation in report.operations if operation.article == "A-1"]
    assert sum(o.sold for o in goods) == 2
    assert sum(o.returned for o in goods) == 1
    assert sum(o.revenue for o in goods) == 200_000
    assert sum(o.commission for o in goods) == -34_000
    assert sum(o.logistics for o in goods) == -44_500
    assert sum(o.other for o in goods) == -6_000  # эквайринг: «Итого» минус всё остальное
    assert sum(o.payout for o in goods) == 115_500
    general = [operation for operation in report.operations if not operation.article]
    assert sum(o.payout for o in general) == -173_040
    assert sum(o.payout for o in report.operations) == -57_540  # совпадает со строкой «Итого» отчёта


def test_unknown_accrual_type_is_reported(tmp_path: Path) -> None:
    report = parse_ozon(write_xlsx(tmp_path / "ozon.xlsx", HEADERS, ROWS, TITLE))
    assert len(report.problems) == 1
    assert "«Корректировка стоимости услуги»" in report.problems[0]


def test_without_quantity_column_each_row_is_one_unit(tmp_path: Path) -> None:
    position = HEADERS.index("Количество")
    headers = HEADERS[:position] + HEADERS[position + 1 :]
    rows = [row[:position] + row[position + 1 :] for row in ROWS]
    report = parse_ozon(write_xlsx(tmp_path / "ozon.xlsx", headers, rows, TITLE))
    assert sum(o.sold for o in report.operations) == 1
    assert sum(o.returned for o in report.operations) == 1
    assert any("нет колонки «Количество»" in problem for problem in report.problems)


def test_wb_report_is_not_taken_for_ozon(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "wb.xlsx", ("Артикул поставщика", "Обоснование для оплаты"), [("A-1", "Продажа")])
    with pytest.raises(ReportFormatError, match="«Тип начисления»"):
        parse_ozon(path)
