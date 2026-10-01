"""Окно проверяется без экрана (QT_QPA_PLATFORM=offscreen): загрузка, пересчёт, ввод, экспорт."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from pytestqt.qtbot import QtBot

from unit_economics.demo import DemoFiles
from unit_economics.gui.models import SORT_ROLE
from unit_economics.gui.window import MainWindow
from unit_economics.pnl import ARTICLE_COLUMNS, TaxMode

NBSP = "\u00a0"


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    main = MainWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(main)
    main.messages = []  # type: ignore[attr-defined]
    main._warn = main.messages.append  # type: ignore[method-assign,attr-defined]
    return main


def load(window: MainWindow, demo_files: DemoFiles) -> MainWindow:
    assert window.load_reports("WB", demo_files.wb)
    assert window.load_reports("Ozon", demo_files.ozon)
    assert window.load_costs(demo_files.costs, remember=False)
    return window


def cell(window: MainWindow, row_title: str, column_title: str) -> str:
    table = window.summary_table
    rows = [table.verticalHeaderItem(row).text() for row in range(table.rowCount())]
    columns = [table.horizontalHeaderItem(column).text() for column in range(table.columnCount())]
    return table.item(rows.index(row_title), columns.index(column_title)).text()


def problems(window: MainWindow) -> list[str]:
    return [window.problems.item(row).text() for row in range(window.problems.count())]


def test_demo_data_fills_every_tab(window: MainWindow, demo_files: DemoFiles) -> None:
    load(window, demo_files)
    assert window.articles_model.rowCount() == 10
    headers = [window.summary_table.horizontalHeaderItem(column).text() for column in range(3)]
    assert headers == ["WB", "Ozon", "Итого"]
    series = window.chart_view.chart().series()
    assert len(series) == 1
    assert [bar_set.label() for bar_set in series[0].barSets()] == ["WB", "Ozon"]
    assert window.costs_table.rowCount() == 5
    assert window.tabs.tabText(3).startswith("Проблемы (")
    assert window.action_export.isEnabled()
    assert "WB: 2 файла" in window.files_label.text()


def test_tax_mode_switch_recalculates(window: MainWindow, demo_files: DemoFiles) -> None:
    load(window, demo_files)
    window.tax_mode.setCurrentIndex(window.tax_mode.findData(TaxMode.PROFIT.value))
    assert cell(window, "Налог", "WB") == "—"
    assert cell(window, "Налог", "Итого") != "—"
    window.tax_mode.setCurrentIndex(window.tax_mode.findData(TaxMode.NONE.value))
    assert cell(window, "Налог", "Итого") == f"0,00{NBSP}₽"
    assert not window.tax_rate.isEnabled()


def test_ads_fields_are_checked_each_on_its_own(window: MainWindow, demo_files: DemoFiles) -> None:
    load(window, demo_files)
    before = cell(window, "Реклама (введена вручную)", "WB")
    window.ads_inputs["WB"].setText("1 500,50")
    window.ads_inputs["Ozon"].setText("abc")
    window.recalculate()
    assert "Реклама Ozon" in window.ads_error.text()
    assert "Реклама WB" not in window.ads_error.text()
    assert window.ads_inputs["WB"].styleSheet() == ""
    assert window.ads_inputs["Ozon"].styleSheet() != ""
    assert cell(window, "Реклама (введена вручную)", "WB") == before  # пока в поле ошибка, цифры не меняются
    window.ads_inputs["Ozon"].setText("2000")
    window.recalculate()
    assert window.ads_error.isHidden()
    assert cell(window, "Реклама (введена вручную)", "WB") == f"−1{NBSP}500,50{NBSP}₽"


def test_cost_edited_in_the_table(window: MainWindow, demo_files: DemoFiles) -> None:
    load(window, demo_files)
    assert any(problem.startswith("Не задана себестоимость: SK-LN") for problem in problems(window))
    row = next(r for r in range(window.costs_table.rowCount()) if window.costs_table.item(r, 0).text() == "SK-LN")
    window.costs_table.item(row, 2).setText("дорого")
    assert window.costs_table.item(row, 2).background().color().name() == "#fbe3e3"
    assert "SK-LN" not in window.costs
    window.costs_table.item(row, 2).setText("900")
    assert window.costs["SK-LN"] == 90_000
    assert not any(problem.startswith("Не задана себестоимость") for problem in problems(window))


def test_broken_report_is_explained(window: MainWindow, tmp_path: Path) -> None:
    broken = tmp_path / "отчёт.xlsx"
    broken.write_text("не Excel", encoding="utf-8")
    assert not window.load_reports("WB", [broken])
    assert "Не удалось открыть" in window.messages[0]  # type: ignore[attr-defined]
    assert window.pnl is None


def test_search_and_numeric_sorting(window: MainWindow, demo_files: DemoFiles) -> None:
    load(window, demo_files)
    window.search.setText("pl-150")
    assert window.articles_proxy.rowCount() == 2
    window.search.clear()
    column = [title for title, _, _ in ARTICLE_COLUMNS].index("Маржинальная прибыль")
    window.articles_view.sortByColumn(column, Qt.SortOrder.AscendingOrder)
    proxy = window.articles_proxy
    values = [proxy.index(row, column).data(SORT_ROLE) for row in range(proxy.rowCount())]
    assert values == sorted(values)
    assert values[0] < 0  # убыточное полотенце на Ozon — первым


def test_export_through_the_dialog(window: MainWindow, demo_files: DemoFiles, tmp_path: Path) -> None:
    load(window, demo_files)
    target = tmp_path / "итог.xlsx"
    window._ask_save_file = lambda *args: target  # type: ignore[method-assign]
    window.export_to_file()
    assert target.exists()
    assert "Сохранено" in window.statusBar().currentMessage()


def test_costs_are_remembered_between_launches(qtbot: QtBot, tmp_path: Path, demo_files: DemoFiles) -> None:
    settings = str(tmp_path / "settings.ini")
    first = MainWindow(QSettings(settings, QSettings.Format.IniFormat))
    qtbot.addWidget(first)
    assert first.load_costs(demo_files.costs)
    first.store.sync()
    second = MainWindow(QSettings(settings, QSettings.Format.IniFormat))
    qtbot.addWidget(second)
    assert second.costs == first.costs


def test_demo_button(window: MainWindow) -> None:
    window.load_demo()
    assert window.articles_model.rowCount() == 10
    assert "Демо-данные загружены" in window.statusBar().currentMessage()
