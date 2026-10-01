from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import pytest
from openpyxl import Workbook

from unit_economics import demo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # окна рисуются без экрана — и в CI тоже


def write_xlsx(
    path: Path,
    headers: Sequence[object],
    rows: Sequence[Sequence[object]],
    title: Sequence[Sequence[object]] = (),
) -> Path:
    workbook = Workbook()
    sheet = workbook.create_sheet("Отчёт", 0)
    del workbook["Sheet"]
    for line in title:
        sheet.append(list(line))
    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))
    workbook.save(path)
    return path


@pytest.fixture(scope="session")
def demo_files(tmp_path_factory: pytest.TempPathFactory) -> demo.DemoFiles:
    return demo.write_demo(tmp_path_factory.mktemp("demo"))
