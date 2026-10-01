"""Прибыль по артикулам и площадкам: операции + себестоимость + настройки (налог, реклама).

Сводка идёт сверху вниз, как P&L: выручка → комиссия, логистика, прочее → к перечислению за товары →
себестоимость → маржинальная прибыль → общие расходы площадки и реклама → прибыль до налога → налог.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

import pandas as pd

from unit_economics.fmt import Kind, Value, plural
from unit_economics.operations import Operation, ParsedReport, format_period, period_of

PLATFORMS = ("WB", "Ozon")
TOTAL = "Итого"
MONEY = ["revenue", "commission", "logistics", "other"]
COUNTS = ["sold", "returned"]
MIN_TAX_RATE = Decimal(1)  # на УСН «доходы минус расходы» налог не меньше 1% доходов
LIST_LIMIT = 8
FILES = ("файл", "файла", "файлов")


class TaxMode(StrEnum):
    NONE = "Без налога"
    INCOME = "УСН «Доходы»"
    PROFIT = "УСН «Доходы минус расходы»"


@dataclass(frozen=True)
class Settings:
    tax_mode: TaxMode = TaxMode.INCOME
    tax_rate: Decimal = Decimal(6)  # процентов
    ads: Mapping[str, int] = field(default_factory=dict)  # площадка → реклама за период, копейки


def percent_of(amount: int, rate: Decimal) -> int:
    return int((Decimal(amount) * rate / 100).quantize(Decimal(1), ROUND_HALF_UP))


def _share(part: int, whole: int | None) -> float | None:
    """Доля с защитой от деления на ноль: неделя без продаж не роняет расчёт."""
    return part / whole if whole is not None and whole > 0 else None


@dataclass(frozen=True)
class ArticleRow:
    platform: str
    article: str
    name: str
    sold: int
    returned: int
    revenue: int
    commission: int
    logistics: int
    other: int
    unit_cost: int | None  # None — себестоимость не задана

    @property
    def payout(self) -> int:
        return self.revenue + self.commission + self.logistics + self.other

    @property
    def net_units(self) -> int:
        return self.sold - self.returned

    @property
    def cogs(self) -> int | None:
        return None if self.unit_cost is None else self.unit_cost * self.net_units

    @property
    def margin_profit(self) -> int:
        return self.payout - (self.cogs or 0)

    @property
    def return_rate(self) -> float | None:
        return _share(self.returned, self.sold)

    @property
    def margin(self) -> float | None:
        return _share(self.margin_profit, self.revenue)

    @property
    def roi(self) -> float | None:
        return _share(self.margin_profit, self.cogs)

    @property
    def profit_per_unit(self) -> int | None:
        if self.net_units <= 0:
            return None
        return int((Decimal(self.margin_profit) / self.net_units).quantize(Decimal(1), ROUND_HALF_UP))


@dataclass(frozen=True)
class Totals:
    platform: str
    sold: int
    returned: int
    revenue: int
    commission: int
    logistics: int
    other: int
    cogs: int
    general: int  # строки без артикула: хранение, приёмка, услуги площадки; со знаком
    ads: int  # реклама, введённая вручную, — расход
    tax: int | None  # None — налог считается только с общей прибыли

    @property
    def payout(self) -> int:
        return self.revenue + self.commission + self.logistics + self.other

    @property
    def margin_profit(self) -> int:
        return self.payout - self.cogs

    @property
    def profit_before_tax(self) -> int:
        return self.margin_profit + self.general - self.ads

    @property
    def net_profit(self) -> int | None:
        return None if self.tax is None else self.profit_before_tax - self.tax

    @property
    def return_rate(self) -> float | None:
        return _share(self.returned, self.sold)

    @property
    def sales_margin(self) -> float | None:
        return None if self.net_profit is None else _share(self.net_profit, self.revenue)


@dataclass(frozen=True)
class Pnl:
    articles: tuple[ArticleRow, ...]
    totals: tuple[Totals, ...]  # по площадкам и «Итого»
    general: tuple[tuple[str, str, int], ...]  # (площадка, операция, сумма)
    problems: tuple[str, ...]
    missing_costs: tuple[str, ...]
    title: str


SUMMARY_ROWS: tuple[tuple[str, Callable[[Totals], Value], Kind], ...] = (
    ("Продано, шт.", lambda t: t.sold, "count"),
    ("Возвраты, шт.", lambda t: t.returned, "count"),
    ("Возвраты, % от продаж", lambda t: t.return_rate, "percent"),
    ("Выручка", lambda t: t.revenue, "money"),
    ("Комиссия площадки", lambda t: t.commission, "money"),
    ("Логистика", lambda t: t.logistics, "money"),
    ("Прочие удержания и доплаты по товарам", lambda t: t.other, "money"),
    ("К перечислению за товары", lambda t: t.payout, "money"),
    ("Себестоимость проданного", lambda t: -t.cogs, "money"),
    ("Маржинальная прибыль", lambda t: t.margin_profit, "money"),
    ("Общие расходы площадки", lambda t: t.general, "money"),
    ("Реклама (введена вручную)", lambda t: -t.ads, "money"),
    ("Прибыль до налога", lambda t: t.profit_before_tax, "money"),
    ("Налог", lambda t: None if t.tax is None else -t.tax, "money"),
    ("Чистая прибыль", lambda t: t.net_profit, "money"),
    ("Рентабельность продаж", lambda t: t.sales_margin, "percent"),
)

ARTICLE_COLUMNS: tuple[tuple[str, Callable[[ArticleRow], Value], Kind], ...] = (
    ("Площадка", lambda a: a.platform, "text"),
    ("Артикул", lambda a: a.article, "text"),
    ("Название", lambda a: a.name, "text"),
    ("Продано", lambda a: a.sold, "count"),
    ("Возвраты", lambda a: a.returned, "count"),
    ("Возвраты, %", lambda a: a.return_rate, "percent"),
    ("Выручка", lambda a: a.revenue, "money"),
    ("Комиссия", lambda a: a.commission, "money"),
    ("Логистика", lambda a: a.logistics, "money"),
    ("Прочее", lambda a: a.other, "money"),
    ("К перечислению", lambda a: a.payout, "money"),
    ("Себестоимость ед.", lambda a: a.unit_cost, "money"),
    ("Себестоимость", lambda a: None if a.cogs is None else -a.cogs, "money"),
    ("Маржинальная прибыль", lambda a: a.margin_profit, "money"),
    ("Маржа", lambda a: a.margin, "percent"),
    ("ROI", lambda a: a.roi, "percent"),
    ("Прибыль на ед.", lambda a: a.profit_per_unit, "money"),
)


def _first_text(values: pd.Series) -> str:
    return next((str(value) for value in values if value), "")


def _platform_order(platform: str) -> tuple[int, str]:
    return (PLATFORMS.index(platform) if platform in PLATFORMS else len(PLATFORMS), platform)


def _articles(frame: pd.DataFrame, costs: Mapping[str, int]) -> tuple[ArticleRow, ...]:
    goods = frame[frame["article"] != ""]
    if goods.empty:
        return ()
    grouped = goods.groupby(["platform", "article"], sort=False).agg(
        name=("name", _first_text), **{column: (column, "sum") for column in COUNTS + MONEY}
    )
    rows = [
        ArticleRow(
            platform=str(record["platform"]),
            article=str(record["article"]),
            name=str(record["name"]),
            sold=int(record["sold"]),
            returned=int(record["returned"]),
            revenue=int(record["revenue"]),
            commission=int(record["commission"]),
            logistics=int(record["logistics"]),
            other=int(record["other"]),
            unit_cost=costs.get(str(record["article"])),
        )
        for record in grouped.reset_index().to_dict("records")
    ]
    return tuple(sorted(rows, key=lambda row: (_platform_order(row.platform), row.article)))


def _general(frame: pd.DataFrame) -> tuple[tuple[str, str, int], ...]:
    rest = frame[frame["article"] == ""]
    if rest.empty:
        return ()
    sums = rest.groupby(["platform", "operation"], sort=True)["payout"].sum().reset_index()
    return tuple((str(r["platform"]), str(r["operation"]), int(r["payout"])) for r in sums.to_dict("records"))


def _totals(platform: str, rows: Sequence[ArticleRow], general: int, ads: int) -> Totals:
    return Totals(
        platform=platform,
        sold=sum(row.sold for row in rows),
        returned=sum(row.returned for row in rows),
        revenue=sum(row.revenue for row in rows),
        commission=sum(row.commission for row in rows),
        logistics=sum(row.logistics for row in rows),
        other=sum(row.other for row in rows),
        cogs=sum(row.cogs or 0 for row in rows),
        general=general,
        ads=ads,
        tax=None,
    )


def _with_taxes(totals: list[Totals], overall: Totals, settings: Settings) -> tuple[list[Totals], Totals]:
    rate = settings.tax_rate
    if settings.tax_mode is TaxMode.NONE:
        return [replace(t, tax=0) for t in totals], replace(overall, tax=0)
    if settings.tax_mode is TaxMode.INCOME:  # база — выручка по цене продавца за вычетом возвратов
        taxed = [replace(t, tax=percent_of(max(t.revenue, 0), rate)) for t in totals]
        return taxed, replace(overall, tax=sum(t.tax or 0 for t in taxed))
    tax = max(
        percent_of(max(overall.profit_before_tax, 0), rate),
        percent_of(max(overall.revenue, 0), MIN_TAX_RATE),
    )
    return totals, replace(overall, tax=tax)


def _listing(items: Sequence[str]) -> str:
    shown = ", ".join(items[:LIST_LIMIT])
    return shown + (f" и ещё {len(items) - LIST_LIMIT}" if len(items) > LIST_LIMIT else "")


def build_pnl(reports: Sequence[ParsedReport], costs: Mapping[str, int], settings: Settings) -> Pnl:
    operations = [operation for report in reports for operation in report.operations]
    frame = pd.DataFrame([asdict(o) for o in operations], columns=[f.name for f in fields(Operation)])
    frame[COUNTS + MONEY] = frame[COUNTS + MONEY].astype("int64")
    frame["payout"] = frame[MONEY].sum(axis=1)
    articles = _articles(frame, costs)
    general = _general(frame)
    present = sorted({o.platform for o in operations}, key=_platform_order)
    totals = [
        _totals(
            platform,
            [row for row in articles if row.platform == platform],
            sum(amount for owner, _, amount in general if owner == platform),
            settings.ads.get(platform, 0),
        )
        for platform in present
    ]
    overall = _totals(TOTAL, articles, sum(amount for _, _, amount in general), sum(t.ads for t in totals))
    totals, overall = _with_taxes(totals, overall, settings)

    problems: list[str] = []
    missing = tuple(sorted({row.article for row in articles if row.unit_cost is None and (row.sold or row.returned)}))
    if missing:
        problems.append(f"Не задана себестоимость: {_listing(missing)} — маржинальная прибыль по ним завышена")
    losing = [
        f"{row.platform} {row.article}" for row in articles if row.unit_cost is not None and row.margin_profit < 0
    ]
    if losing:
        problems.append(f"Убыточные артикулы (маржинальная прибыль меньше нуля): {_listing(losing)}")
    periods: dict[str, tuple[date, date] | None] = {}
    for platform in present:
        own = [report for report in reports if report.platform == platform]
        periods[platform] = period_of(day for report in own if report.period for day in report.period)
    known = {platform: period for platform, period in periods.items() if period is not None}
    if len(set(known.values())) > 1:
        described = ", ".join(f"{platform} {format_period(period)}" for platform, period in known.items())
        problems.append(f"Периоды отчётов разные: {described} — сравнивайте площадки с осторожностью")
    problems.extend(problem for report in reports for problem in report.problems)

    title = " · ".join(
        f"{platform}: {format_period(periods[platform])}, "
        f"{(count := sum(r.platform == platform for r in reports))} {plural(count, FILES)}"
        for platform in present
    )
    return Pnl(articles, (*totals, overall), general, tuple(problems), missing, title)
