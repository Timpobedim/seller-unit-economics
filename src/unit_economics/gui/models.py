"""Модель таблицы артикулов для QTableView: текст по-русски, сортировка по числам, подсветка убытков."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from unit_economics.fmt import format_value
from unit_economics.pnl import ARTICLE_COLUMNS, ArticleRow

SORT_ROLE = Qt.ItemDataRole.UserRole
LOSS = QColor("#fbe3e3")
MISSING = QColor("#fff4d6")
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_ROOT = QModelIndex()


class ArticlesModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[ArticleRow] = []

    def set_rows(self, rows: Sequence[ArticleRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(ARTICLE_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return ARTICLE_COLUMNS[section][0]
        return None

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        title, getter, kind = ARTICLE_COLUMNS[index.column()]
        value = getter(row)
        if role == Qt.ItemDataRole.DisplayRole:
            return format_value(value, kind)
        if role == SORT_ROLE:  # сортируем числа как числа, пустые — в конец списка по убыванию
            return value if value is not None else ("" if kind == "text" else float("-inf"))
        if role == Qt.ItemDataRole.TextAlignmentRole and kind != "text":
            return RIGHT
        if role == Qt.ItemDataRole.BackgroundRole:
            if row.margin_profit < 0:
                return QBrush(LOSS)
            if row.unit_cost is None and title.startswith("Себестоимость"):
                return QBrush(MISSING)
        if role == Qt.ItemDataRole.ToolTipRole and row.unit_cost is None:
            return "Себестоимость не задана — маржинальная прибыль завышена"
        return None
