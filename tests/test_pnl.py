from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from unit_economics.operations import Operation, ParsedReport
from unit_economics.pnl import TOTAL, Pnl, Settings, TaxMode, Totals, build_pnl

WB = (
    Operation("WB", "A-1", "Плед", "Продажа", sold=3, revenue=300_000, commission=-75_000),
    Operation("WB", "A-1", "Плед", "Возврат", returned=1, revenue=-100_000, commission=25_000),
    Operation("WB", "A-1", "Плед", "Логистика", logistics=-30_000),
    Operation("WB", "", "", "Хранение", other=-50_000),
)
OZON = (
    Operation("Ozon", "A-1", "Плед", "Доставка покупателю", sold=2, revenue=200_000, commission=-34_000,
              logistics=-40_000),
    Operation("Ozon", "A-1", "Плед", "Оплата эквайринга", other=-6_000),
    Operation("Ozon", "B-2", "Наволочка", "Доставка покупателю", sold=1, revenue=50_000, commission=-8_000,
              logistics=-9_000),
)  # fmt: skip
COSTS = {"A-1": 50_000}
SEPTEMBER = (date(2026, 9, 1), date(2026, 9, 7))
AUGUST = (date(2026, 8, 1), date(2026, 8, 31))


def report(platform: str, operations: tuple[Operation, ...], period: tuple[date, date] | None) -> ParsedReport:
    return ParsedReport(platform, f"{platform}.xlsx", operations, (), period, len(operations))


def pnl(settings: Settings, wb_period: tuple[date, date] | None = SEPTEMBER) -> Pnl:
    return build_pnl([report("WB", WB, wb_period), report("Ozon", OZON, AUGUST)], COSTS, settings)


def totals(result: Pnl, platform: str) -> Totals:
    return next(t for t in result.totals if t.platform == platform)


def test_article_economics() -> None:
    row = next(a for a in pnl(Settings()).articles if (a.platform, a.article) == ("WB", "A-1"))
    assert (row.sold, row.returned, row.net_units) == (3, 1, 2)
    assert (row.revenue, row.payout, row.cogs, row.margin_profit) == (200_000, 120_000, 100_000, 20_000)
    assert row.margin == pytest.approx(0.1)
    assert row.roi == pytest.approx(0.2)
    assert row.profit_per_unit == 10_000
    assert row.return_rate == pytest.approx(1 / 3)


def test_missing_cost_is_flagged_not_treated_as_free() -> None:
    result = pnl(Settings())
    row = next(a for a in result.articles if a.article == "B-2")
    assert (row.unit_cost, row.cogs, row.margin_profit) == (None, None, 33_000)
    assert result.missing_costs == ("B-2",)
    assert result.problems[0].startswith("Не задана себестоимость: B-2")


def test_income_tax_is_counted_per_platform() -> None:
    result = pnl(Settings(TaxMode.INCOME, Decimal(6), {"WB": 5_000}))
    wb, ozon, total = totals(result, "WB"), totals(result, "Ozon"), totals(result, TOTAL)
    assert (wb.general, wb.ads, wb.profit_before_tax, wb.tax, wb.net_profit) == (
        -50_000,
        5_000,
        -35_000,
        12_000,
        -47_000,
    )
    assert wb.sales_margin == pytest.approx(-0.235)
    assert (ozon.margin_profit, ozon.tax, ozon.net_profit) == (53_000, 15_000, 38_000)
    assert (total.revenue, total.profit_before_tax, total.tax, total.net_profit) == (450_000, 18_000, 27_000, -9_000)


def test_profit_tax_is_counted_once_with_one_percent_minimum() -> None:
    result = pnl(Settings(TaxMode.PROFIT, Decimal(15), {"WB": 5_000}))
    assert totals(result, "WB").tax is None  # с одной площадки налог «доходы минус расходы» не считают
    assert totals(result, "WB").net_profit is None
    total = totals(result, TOTAL)
    assert total.tax == 4_500  # 15% от 180 ₽ = 27 ₽ меньше минимального 1% от 4 500 ₽ выручки
    assert total.net_profit == 13_500


def test_without_tax() -> None:
    assert {t.tax for t in pnl(Settings(TaxMode.NONE)).totals} == {0}


def test_article_with_only_returns_does_not_divide_by_zero() -> None:
    returns_only = (Operation("WB", "C-3", "Скатерть", "Возврат", returned=1, revenue=-100_000, commission=25_000),)
    result = build_pnl([report("WB", returns_only, SEPTEMBER)], {"C-3": 40_000}, Settings())
    row = result.articles[0]
    assert (row.return_rate, row.margin, row.roi, row.profit_per_unit) == (None, None, None, None)
    assert totals(result, TOTAL).sales_margin is None


def test_losses_and_different_periods_are_pointed_out() -> None:
    expensive = {"A-1": 90_000}
    result = build_pnl([report("WB", WB, SEPTEMBER), report("Ozon", OZON, AUGUST)], expensive, Settings())
    assert any(problem.startswith("Убыточные артикулы") and "WB A-1" in problem for problem in result.problems)
    assert any(problem.startswith("Периоды отчётов разные") for problem in result.problems)
    assert result.title == "WB: 01.09–07.09.2026, 1 файл · Ozon: 01.08–31.08.2026, 1 файл"
