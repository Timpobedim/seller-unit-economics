"""Главное окно: отчёты, себестоимость, налог и реклама, итоги с графиком, таблица артикулов, экспорт.

Расчёт живёт в unit_economics.pnl, окно только собирает ввод и показывает результат. Каждое поле
проверяется само по себе.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

from PySide6.QtCharts import QChartView
from PySide6.QtCore import QSettings, QSortFilterProxyModel, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from unit_economics import costs as cost_files
from unit_economics import demo
from unit_economics.columns import ReportFormatError
from unit_economics.export import ExportError, export_report
from unit_economics.fmt import format_amount, format_value, plural
from unit_economics.gui.chart import profit_chart
from unit_economics.gui.models import SORT_ROLE, ArticlesModel
from unit_economics.money import MoneyError, to_kopecks
from unit_economics.operations import ParsedReport, format_period, period_of
from unit_economics.ozon import parse_ozon
from unit_economics.pnl import FILES, PLATFORMS, SUMMARY_ROWS, ArticleRow, Pnl, Settings, TaxMode, build_pnl
from unit_economics.wb import parse_wb

PARSERS: dict[str, Callable[[Path], ParsedReport]] = {"WB": parse_wb, "Ozon": parse_ozon}
DIALOG_TITLES = {"WB": "Детализация еженедельного отчёта WB", "Ozon": "Отчёт о начислениях Ozon"}
ERROR_STYLE = "border: 1px solid #d03b3b;"
INVALID = QColor("#fbe3e3")
NEGATIVE = QColor("#b3261e")
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
COST_COLUMN = 2
PROBLEMS_TAB = 3


class MainWindow(QMainWindow):
    def __init__(self, store: QSettings | None = None) -> None:
        super().__init__()
        self.store = store if store is not None else QSettings()
        self.reports: dict[str, list[ParsedReport]] = {platform: [] for platform in PLATFORMS}
        self.costs: dict[str, int] = {}
        self.pnl: Pnl | None = None
        self._filling = False
        self.setWindowTitle("Юнит-экономика WB и Ozon")
        self._build_toolbar()
        self._build_body()
        self._restore_costs()
        self.recalculate()

    # --- построение окна -------------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        toolbar = self.addToolBar("Файлы")
        toolbar.setMovable(False)

        def action(title: str, slot: Callable[[], None], tip: str) -> QAction:
            item = QAction(title, self)
            item.setToolTip(tip)
            item.triggered.connect(slot)
            toolbar.addAction(item)
            return item

        self.action_wb = action(
            "Отчёт WB…", self.open_wb, "Детализация еженедельного отчёта WB (.xlsx), можно несколько"
        )
        self.action_ozon = action("Отчёт Ozon…", self.open_ozon, "Отчёт о начислениях Ozon (.xlsx)")
        toolbar.addSeparator()
        self.action_costs = action(
            "Себестоимость…", self.open_costs, "CSV или XLSX с колонками «Артикул» и «Себестоимость»"
        )
        self.action_save_costs = action("Сохранить себестоимость…", self.save_costs_to_file, "Сохранить таблицу в CSV")
        toolbar.addSeparator()
        self.action_export = action("Экспорт в Excel…", self.export_to_file, "Итоги и таблица артикулов в .xlsx")
        toolbar.addSeparator()
        self.action_demo = action("Демо-данные", self.load_demo, "Синтетические отчёты, чтобы посмотреть приложение")

    def _build_body(self) -> None:
        panel = QWidget()
        form = QFormLayout(panel)
        self.tax_mode = QComboBox()
        for mode in TaxMode:
            self.tax_mode.addItem(mode.value, mode.value)
        self.tax_mode.setCurrentIndex(self.tax_mode.findData(Settings().tax_mode.value))  # как в расчёте по умолчанию
        self.tax_mode.currentIndexChanged.connect(self._on_tax_mode)
        self.tax_rate = QDoubleSpinBox()
        self.tax_rate.setRange(0, 20)
        self.tax_rate.setDecimals(1)
        self.tax_rate.setSingleStep(0.5)
        self.tax_rate.setSuffix(" %")
        self.tax_rate.setValue(6)
        self.tax_rate.valueChanged.connect(self.recalculate)
        form.addRow("Налог", self.tax_mode)
        form.addRow("Ставка", self.tax_rate)
        self.ads_inputs: dict[str, QLineEdit] = {}
        for platform in PLATFORMS:
            field = QLineEdit()
            field.setPlaceholderText("0,00")
            field.setToolTip("Расходы на рекламу за период отчёта, например «15 000» или «1500,50»")
            field.editingFinished.connect(self.recalculate)
            self.ads_inputs[platform] = field
            form.addRow(f"Реклама {platform}, ₽", field)
        self.ads_error = QLabel()
        self.ads_error.setWordWrap(True)
        self.ads_error.setStyleSheet("color: #b3261e;")
        self.ads_error.hide()
        form.addRow(self.ads_error)
        self.files_label = QLabel()
        self.files_label.setWordWrap(True)
        form.addRow(self.files_label)

        self.summary_table = QTableWidget()
        self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.chart_view = QChartView()
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setMinimumHeight(260)
        summary = QSplitter(Qt.Orientation.Vertical)
        summary.addWidget(self.summary_table)
        summary.addWidget(self.chart_view)

        self.articles_model = ArticlesModel()
        self.articles_proxy = QSortFilterProxyModel(self)
        self.articles_proxy.setSourceModel(self.articles_model)
        self.articles_proxy.setSortRole(SORT_ROLE)
        self.articles_proxy.setFilterKeyColumn(-1)
        self.articles_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.articles_view = QTableView()
        self.articles_view.setModel(self.articles_proxy)
        self.articles_view.setSortingEnabled(True)
        self.articles_view.setAlternatingRowColors(True)
        self.articles_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по артикулу или названию")
        self.search.textChanged.connect(self.articles_proxy.setFilterFixedString)
        articles = QWidget()
        layout = QVBoxLayout(articles)
        layout.addWidget(self.search)
        layout.addWidget(self.articles_view)

        self.costs_table = QTableWidget(0, 3)
        self.costs_table.setHorizontalHeaderLabels(["Артикул", "Название", "Себестоимость, ₽"])
        self.costs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.costs_table.itemChanged.connect(self._on_cost_edited)
        self.problems = QListWidget()
        self.problems.setWordWrap(True)

        self.tabs = QTabWidget()
        self.tabs.addTab(summary, "Итоги")
        self.tabs.addTab(articles, "По артикулам")
        self.tabs.addTab(self.costs_table, "Себестоимость")
        self.tabs.addTab(self.problems, "Проблемы")
        body = QSplitter(Qt.Orientation.Horizontal)
        body.addWidget(panel)
        body.addWidget(self.tabs)
        body.setStretchFactor(1, 1)
        body.setSizes([290, 1030])
        self.setCentralWidget(body)
        self.statusBar().showMessage("Откройте детализацию отчёта WB и/или отчёт о начислениях Ozon — или демо-данные")

    # --- диалоги (в тестах подменяются) -----------------------------------------------------------

    def _last_dir(self) -> str:
        return str(self.store.value("paths/last_dir", str(Path.home())))

    def _remember_dir(self, path: Path) -> None:
        self.store.setValue("paths/last_dir", str(path.parent))

    def _ask_open_files(self, title: str, pattern: str) -> list[Path]:
        names, _ = QFileDialog.getOpenFileNames(self, title, self._last_dir(), pattern)
        return [Path(name) for name in names]

    def _ask_save_file(self, title: str, name: str, pattern: str) -> Path | None:
        selected, _ = QFileDialog.getSaveFileName(self, title, str(Path(self._last_dir()) / name), pattern)
        return Path(selected) if selected else None

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "Юнит-экономика", text)

    # --- отчёты ------------------------------------------------------------------------------------

    def open_wb(self) -> None:
        self._open_reports("WB")

    def open_ozon(self) -> None:
        self._open_reports("Ozon")

    def _open_reports(self, platform: str) -> None:
        paths = self._ask_open_files(DIALOG_TITLES[platform], "Книга Excel (*.xlsx)")
        if paths:
            self.load_reports(platform, paths)

    def load_reports(self, platform: str, paths: Sequence[Path]) -> bool:
        """Заменяет отчёты площадки. Файл с ошибкой не загружается вовсе — вместо полупосчитанного итога."""
        loaded: list[ParsedReport] = []
        for path in paths:
            try:
                loaded.append(PARSERS[platform](path))
            except ReportFormatError as exc:
                self._warn(str(exc))
                return False
        self.reports[platform] = loaded
        if paths:
            self._remember_dir(paths[0])
        self._fill_costs()
        self.recalculate()
        return True

    # --- себестоимость -----------------------------------------------------------------------------

    def open_costs(self) -> None:
        paths = self._ask_open_files("Себестоимость", "Таблица (*.csv *.xlsx)")
        if paths:
            self.load_costs(paths[0])

    def load_costs(self, path: Path, *, remember: bool = True) -> bool:
        try:
            self.costs = cost_files.load_costs(path)
        except cost_files.CostsError as exc:
            self._warn(str(exc))
            return False
        if remember:
            self.store.setValue("paths/costs", str(path))
            self._remember_dir(path)
        self._fill_costs()
        self.recalculate()
        self.statusBar().showMessage(f"Себестоимость: {path.name}, артикулов — {len(self.costs)}")
        return True

    def save_costs_to_file(self) -> None:
        path = self._ask_save_file("Сохранить себестоимость", "себестоимость.csv", "CSV (*.csv)")
        if path is None:
            return
        try:
            cost_files.save_costs(path, self.costs, self._names())
        except cost_files.CostsError as exc:
            self._warn(str(exc))
            return
        self.store.setValue("paths/costs", str(path))
        self.statusBar().showMessage(f"Себестоимость сохранена: {path}")

    def _restore_costs(self) -> None:
        saved = self.store.value("paths/costs")
        if not saved or not Path(str(saved)).exists():
            return
        try:
            self.costs = cost_files.load_costs(Path(str(saved)))
        except cost_files.CostsError as exc:
            self.statusBar().showMessage(f"Себестоимость не загружена: {exc}")

    def _names(self) -> dict[str, str]:
        names: dict[str, str] = {}
        for reports in self.reports.values():
            for report in reports:
                for operation in report.operations:
                    if operation.article and not names.get(operation.article):
                        names[operation.article] = operation.name
        return names

    def _fill_costs(self) -> None:
        names = self._names()
        articles = sorted(set(names) | set(self.costs))
        self._filling = True
        try:
            self.costs_table.setRowCount(len(articles))
            for row, article in enumerate(articles):
                cost = format_amount(self.costs[article]) if article in self.costs else ""
                for column, value in enumerate((article, names.get(article, ""), cost)):
                    item = QTableWidgetItem(value)
                    if column == COST_COLUMN:
                        item.setTextAlignment(RIGHT)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.costs_table.setItem(row, column, item)
        finally:
            self._filling = False

    def _on_cost_edited(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != COST_COLUMN:
            return
        article_item = self.costs_table.item(item.row(), 0)
        if article_item is None:
            return
        article, value = article_item.text(), item.text().strip()
        try:
            kopecks = to_kopecks(value) if value else None
            if kopecks is not None and kopecks < 0:
                raise MoneyError("себестоимость не может быть отрицательной")
        except MoneyError as exc:
            item.setBackground(QBrush(INVALID))
            self.statusBar().showMessage(f"{article}: {exc}")
            return
        item.setBackground(QBrush())
        if kopecks is None:
            self.costs.pop(article, None)
        else:
            self.costs[article] = kopecks
        self.recalculate()

    # --- расчёт ------------------------------------------------------------------------------------

    def _on_tax_mode(self) -> None:
        self.tax_rate.setEnabled(TaxMode(str(self.tax_mode.currentData())) is not TaxMode.NONE)
        self.recalculate()

    def _settings(self) -> Settings | None:
        ads: dict[str, int] = {}
        errors: list[str] = []
        for platform, field in self.ads_inputs.items():
            value = field.text().strip()
            try:
                amount = to_kopecks(value) if value else 0
                if amount < 0:
                    raise MoneyError("сумма не может быть отрицательной")
            except MoneyError as exc:
                field.setStyleSheet(ERROR_STYLE)
                errors.append(f"Реклама {platform}: {exc}")
                continue
            field.setStyleSheet("")
            ads[platform] = amount
        self.ads_error.setText("\n".join(errors))
        self.ads_error.setVisible(bool(errors))
        if errors:
            return None
        rate = Decimal(str(round(self.tax_rate.value(), 1)))
        return Settings(TaxMode(str(self.tax_mode.currentData())), rate, ads)

    def recalculate(self) -> None:
        settings = self._settings()
        if settings is None:
            return  # в поле ошибка: прежние цифры остаются, пока ввод не исправят
        self._update_files_label()
        reports = [report for platform in PLATFORMS for report in self.reports[platform]]
        if not reports:
            self.pnl = None
            self.summary_table.clear()
            self.summary_table.setRowCount(0)
            self.summary_table.setColumnCount(0)
            self.articles_model.set_rows([])
            self._set_chart([])
            self._fill_problems(())
            self.action_export.setEnabled(False)
            return
        self.pnl = build_pnl(reports, self.costs, settings)
        self._fill_summary(self.pnl)
        self.articles_model.set_rows(self.pnl.articles)
        self._set_chart(self.pnl.articles)
        self._fill_problems(self.pnl.problems)
        self.action_export.setEnabled(True)

    def _fill_summary(self, pnl: Pnl) -> None:
        table = self.summary_table
        table.clear()
        table.setRowCount(len(SUMMARY_ROWS))
        table.setColumnCount(len(pnl.totals))
        table.setHorizontalHeaderLabels([totals.platform for totals in pnl.totals])
        table.setVerticalHeaderLabels([title for title, _, _ in SUMMARY_ROWS])
        for row, (_, getter, kind) in enumerate(SUMMARY_ROWS):
            for column, totals in enumerate(pnl.totals):
                value = getter(totals)
                item = QTableWidgetItem(format_value(value, kind))
                item.setTextAlignment(RIGHT)
                if isinstance(value, int | float) and value < 0 and kind != "count":
                    item.setForeground(QBrush(NEGATIVE))
                table.setItem(row, column, item)

    def _set_chart(self, rows: Sequence[ArticleRow]) -> None:
        previous = self.chart_view.chart()
        self.chart_view.setChart(profit_chart(rows))
        if previous is not None:
            previous.deleteLater()

    def _fill_problems(self, problems: Sequence[str]) -> None:
        self.problems.clear()
        self.problems.addItems(list(problems) or ["Проблем не найдено"])
        self.tabs.setTabText(PROBLEMS_TAB, f"Проблемы ({len(problems)})" if problems else "Проблемы")

    def _update_files_label(self) -> None:
        lines = []
        for platform in PLATFORMS:
            reports = self.reports[platform]
            if reports:
                period = period_of(day for report in reports if report.period for day in report.period)
                lines.append(f"{platform}: {len(reports)} {plural(len(reports), FILES)}, {format_period(period)}")
        self.files_label.setText("\n".join(lines) or "Отчёты не загружены")

    # --- экспорт и демо ----------------------------------------------------------------------------

    def export_to_file(self) -> None:
        if self.pnl is None:
            self._warn("Сначала загрузите отчёты WB или Ozon.")
            return
        path = self._ask_save_file("Экспорт в Excel", "юнит-экономика.xlsx", "Книга Excel (*.xlsx)")
        if path is None:
            return
        try:
            export_report(path, self.pnl)
        except ExportError as exc:
            self._warn(str(exc))
            return
        self._remember_dir(path)
        self.statusBar().showMessage(f"Сохранено: {path}")

    def load_demo(self) -> None:
        files = demo.write_demo(Path(tempfile.mkdtemp(prefix="unit-economics-demo-")))
        if self.load_reports("WB", files.wb) and self.load_reports("Ozon", files.ozon):
            self.load_costs(files.costs, remember=False)  # демо не должно подменять вашу себестоимость
            self.statusBar().showMessage(f"Демо-данные загружены из {files.costs.parent}")
