"""График «Маржинальная прибыль по артикулам»: горизонтальные столбцы, WB и Ozon рядом.

Цвета — первые два слота проверенной категориальной палитры: синий и оранжевый различимы и при
нарушениях цветового зрения. Площадки подписаны в легенде, точные значения — в таблицах рядом.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from PySide6.QtCharts import QBarCategoryAxis, QBarSet, QChart, QHorizontalBarSeries, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from unit_economics.pnl import PLATFORMS, ArticleRow

COLORS = {"WB": "#2a78d6", "Ozon": "#eb6834"}
LIMIT = 12


def profit_chart(rows: Sequence[ArticleRow], limit: int = LIMIT) -> QChart:
    chart = QChart()
    chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
    revenue: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        revenue[row.article] += max(row.revenue, 0)
    top = sorted(revenue, key=lambda article: (-revenue[article], article))[:limit]
    if not top:
        chart.setTitle("Маржинальная прибыль по артикулам — нет данных")
        return chart
    chart.setTitle(f"Маржинальная прибыль по артикулам, ₽ — {len(top)} с наибольшей выручкой")
    order = list(reversed(top))  # у горизонтальных столбцов первая категория рисуется внизу
    series = QHorizontalBarSeries()
    values = [0.0]
    for platform in PLATFORMS:
        profit = {row.article: row.margin_profit / 100 for row in rows if row.platform == platform}
        if not profit:
            continue
        bars = QBarSet(platform)
        bars.setColor(QColor(COLORS[platform]))
        bars.setBorderColor(QColor(COLORS[platform]))
        for article in order:
            bars.append(profit.get(article, 0.0))
            values.append(profit.get(article, 0.0))
        series.append(bars)
    chart.addSeries(series)
    categories = QBarCategoryAxis()
    categories.append(order)
    chart.addAxis(categories, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(categories)
    axis = QValueAxis()
    axis.setLabelFormat("%.0f")
    axis.setRange(min(values) * 1.1, max(values) * 1.1 or 1.0)
    axis.applyNiceNumbers()
    chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom)
    series.attachAxis(axis)
    return chart
