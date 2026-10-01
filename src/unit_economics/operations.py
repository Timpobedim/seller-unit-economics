"""Операции площадок в едином виде: знак суммы — «деньги продавцу» (+) или «с продавца» (−)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from unit_economics.money import is_blank


@dataclass(frozen=True)
class Operation:
    platform: str
    article: str  # пусто — расход площадки без привязки к товару (хранение, реклама, приёмка)
    name: str
    operation: str  # как в отчёте: «Продажа», «Логистика», «Доставка покупателю»…
    sold: int = 0
    returned: int = 0
    revenue: int = 0  # копейки: продажи по цене после скидки продавца, возвраты с минусом
    commission: int = 0
    logistics: int = 0
    other: int = 0  # штрафы, доплаты, компенсации, эквайринг и прочее

    @property
    def payout(self) -> int:
        return self.revenue + self.commission + self.logistics + self.other


@dataclass(frozen=True)
class ParsedReport:
    platform: str
    source: str
    operations: tuple[Operation, ...]
    problems: tuple[str, ...]
    period: tuple[date, date] | None
    rows: int


def to_date(value: object) -> date | None:
    """Дата из ячейки: datetime, Timestamp или строка «01.09.2026» / «2026-09-01»."""
    if is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(str(value), errors="coerce", dayfirst=True)
    return None if pd.isna(parsed) else parsed.date()


def period_of(dates: Iterable[date | None]) -> tuple[date, date] | None:
    known = [day for day in dates if day is not None]
    return (min(known), max(known)) if known else None


def format_period(period: tuple[date, date] | None) -> str:
    if period is None:
        return "период не указан"
    start, end = period
    return f"{start:%d.%m}–{end:%d.%m.%Y}" if start.year == end.year else f"{start:%d.%m.%Y}–{end:%d.%m.%Y}"
