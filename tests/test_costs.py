from __future__ import annotations

from pathlib import Path

import pytest
from conftest import write_xlsx

from unit_economics.costs import CostsError, load_costs, save_costs


def test_csv_with_semicolons_bom_and_decimal_comma(tmp_path: Path) -> None:
    path = tmp_path / "себестоимость.csv"
    path.write_text(
        "Артикул;Название;Себестоимость\nPL-150;Плед;610,00\nNV-5070;Наволочки;1 260,50\nSK-LN;Скатерть;\n",
        encoding="utf-8-sig",
    )
    assert load_costs(path) == {"PL-150": 61_000, "NV-5070": 126_050}  # пустая — «не задана», а не ноль


def test_csv_with_commas_and_dot_decimals(tmp_path: Path) -> None:
    path = tmp_path / "costs.csv"
    path.write_text('Артикул,Себестоимость\nA-1,100.5\nB-2,"1,250.00"\n', encoding="utf-8")
    assert load_costs(path) == {"A-1": 10_050, "B-2": 125_000}


def test_xlsx_table(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "costs.xlsx", ("Артикул поставщика", "Себестоимость, руб."), [("A-1", 99.9), (123, 5)])
    assert load_costs(path) == {"A-1": 9_990, "123": 500}


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("Артикул;Себестоимость\nA-1;10\nA-1;12\n", "дважды"),
        ("Артикул;Себестоимость\nA-1;-10\n", "отрицательной"),
        ("Артикул;Себестоимость\nA-1;10\nB-2;дорого\n", "строка 3"),
        ("Товар;Цена\nA-1;10\n", "нужны колонки"),
    ],
)
def test_mistakes_are_explained(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "costs.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(CostsError, match=message):
        load_costs(path)


def test_saved_file_opens_in_excel_and_loads_back(tmp_path: Path) -> None:
    path = tmp_path / "себестоимость.csv"
    costs = {"PL-150": 61_000, "KPB-15": 135_050}
    save_costs(path, costs, {"PL-150": "Плед"})
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM: Excel сразу понимает UTF-8
    assert "KPB-15;;1350,50" in raw.decode("utf-8-sig")
    assert load_costs(path) == costs
