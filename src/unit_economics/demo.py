"""Демо-данные: две недели детализации WB, месяц начислений Ozon и себестоимость. Всё синтетическое.

Файлы повторяют устройство настоящих отчётов: названия колонок, лишние для расчёта колонки, строки над
заголовками и строку итогов у Ozon. Поэтому демо проходит через тот же разбор, что и реальные выгрузки.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

from unit_economics.costs import save_costs
from unit_economics.money import to_kopecks

WB_HEADERS = (
    "№", "Номер поставки", "Предмет", "Код номенклатуры", "Бренд", "Артикул поставщика", "Название", "Размер",
    "Баркод", "Тип документа", "Обоснование для оплаты", "Дата заказа покупателем", "Дата продажи", "Кол-во",
    "Цена розничная", "Вайлдберриз реализовал Товар (Пр)", "Согласованный продуктовый дисконт, %",
    "Цена розничная с учетом согласованной скидки", "Размер кВВ, %", "К перечислению Продавцу за реализованный Товар",
    "Количество доставок", "Количество возврата", "Услуги по доставке товара покупателю", "Общая сумма штрафов",
    "Доплаты", "Виды логистики, штрафов и доплат", "Хранение", "Удержания", "Платная приемка", "Srid",
)  # fmt: skip
WB_TEXT = frozenset({
    "Номер поставки", "Предмет", "Бренд", "Артикул поставщика", "Название", "Размер", "Баркод", "Тип документа",
    "Обоснование для оплаты", "Дата заказа покупателем", "Дата продажи", "Виды логистики, штрафов и доплат", "Srid",
})  # fmt: skip
PROCESSING = (
    "Обработка отправления (Drop-off/Pick-up) (разбивается по товарам пропорционально количеству в отправлении)"
)
LAST_MILE = "Последняя миля (разбивается по товарам пропорционально доле цены товара в сумме отправления)"
CANCELLED = (
    "Обработка отмененного или невостребованного товара (разбивается по товарам в отправлении в одинаковой пропорции)"
)
OZON_MONEY = (
    "За продажу или возврат до вычета комиссий и услуг", "Комиссия за продажу", "Сборка заказа", PROCESSING,
    "Магистраль", LAST_MILE, "Обратная магистраль", "Обработка возврата", CANCELLED,
    "Обработка невыкупленного товара", "Логистика", "Обратная логистика", "Итого",
)  # fmt: skip
OZON_HEADERS = (
    "ID начисления", "Дата начисления", "Тип начисления", "Номер отправления или идентификатор услуги",
    "Дата принятия заказа в обработку или оказания услуги", "Склад отгрузки", "SKU", "Артикул",
    "Название товара или услуги", "Количество", "За продажу или возврат до вычета комиссий и услуг",
    "Ставка комиссии", "Комиссия за продажу", "Сборка заказа", PROCESSING, "Магистраль", LAST_MILE,
    "Обратная магистраль", "Обработка возврата", CANCELLED, "Обработка невыкупленного товара", "Логистика",
    "Индекс локализации", "Обратная логистика", "Итого",
)  # fmt: skip
OZON_TEXT = frozenset({
    "ID начисления", "Дата начисления", "Тип начисления", "Номер отправления или идентификатор услуги",
    "Дата принятия заказа в обработку или оказания услуги", "Склад отгрузки", "SKU", "Артикул",
    "Название товара или услуги",
})  # fmt: skip
WB_WEEKS = (date(2026, 8, 31), date(2026, 9, 7))
OZON_MONTH = (date(2026, 8, 1), date(2026, 8, 31))


@dataclass(frozen=True)
class Product:
    article: str
    name: str
    subject: str
    price: int  # цена до скидки на WB, ₽
    discount: int  # скидка продавца на WB, %
    kvv: float  # комиссия WB, %
    tariff: float  # логистика WB до покупателя за единицу, ₽
    return_rate: float
    cost: Decimal | None  # себестоимость единицы; None — не задана
    wb_week: int  # продаж на WB в неделю
    ozon_price: int
    ozon_commission: float  # %
    ozon_month: int  # продаж на Ozon в месяц


PRODUCTS = (
    Product("PL-150", "Плед флисовый 150×200", "Пледы", 3490, 45, 24.5, 95.0, 0.06, Decimal("610"), 40, 1990, 17.0, 70),
    Product(
        "KPB-15",
        "Комплект постельного белья 1,5-спальный",
        "Комплекты постельного белья",
        5990,
        50,
        25.5,
        110.0,
        0.08,
        Decimal("1350"),
        25,
        3190,
        18.0,
        45,
    ),
    Product(
        "NV-5070",
        "Наволочки сатин 50×70, 2 шт.",
        "Наволочки",
        1290,
        40,
        24.5,
        65.0,
        0.05,
        Decimal("260"),
        30,
        790,
        16.0,
        50,
    ),
    # дешёвое полотенце: на Ozon логистика и комиссия съедают всю маржу
    Product(
        "PT-VF", "Полотенце вафельное 45×70", "Полотенца", 390, 20, 27.0, 70.0, 0.04, Decimal("140"), 60, 270, 19.0, 90
    ),
    # себестоимость не внесена — приложение должно об этом предупредить
    Product("SK-LN", "Скатерть льняная 140×180", "Скатерти", 2790, 35, 24.5, 80.0, 0.07, None, 12, 1790, 17.0, 20),
)


@dataclass(frozen=True)
class DemoFiles:
    wb: tuple[Path, ...]
    ozon: tuple[Path, ...]
    costs: Path


def _money(value: float) -> float:
    return round(value, 2)


def _wb_rows(start: date, week: int, rng: random.Random) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    end = start + timedelta(days=6)
    for index, product in enumerate(PRODUCTS):
        with_discount = _money(product.price * (100 - product.discount) / 100)
        card = {
            "Предмет": product.subject, "Бренд": "Уютный дом", "Артикул поставщика": product.article,
            "Название": product.name, "Код номенклатуры": 190_000_000 + index * 3571, "Баркод": f"20400{index:08d}",
        }  # fmt: skip
        for _ in range(rng.randint(round(product.wb_week * 0.8), round(product.wb_week * 1.2))):
            quantity = 2 if rng.random() < 0.05 else 1
            day = start + timedelta(days=rng.randrange(7))
            sold = {**card, "Дата продажи": day, "Дата заказа покупателем": day - timedelta(days=rng.randint(1, 4))}
            price = {
                "Цена розничная": product.price, "Согласованный продуктовый дисконт, %": product.discount,
                "Цена розничная с учетом согласованной скидки": with_discount, "Размер кВВ, %": product.kvv,
            }  # fmt: skip
            rows.append({
                **sold, **price, "Тип документа": "Продажа", "Обоснование для оплаты": "Продажа", "Кол-во": quantity,
                "Вайлдберриз реализовал Товар (Пр)": _money(with_discount * quantity * 0.9),
                "К перечислению Продавцу за реализованный Товар": _money(
                    with_discount * quantity * (100 - product.kvv) / 100
                ),
            })  # fmt: skip
            rows.append({
                **sold, "Обоснование для оплаты": "Логистика", "Количество доставок": quantity,
                "Услуги по доставке товара покупателю": _money(product.tariff * quantity),
                "Виды логистики, штрафов и доплат": "К клиенту при продаже",
            })  # fmt: skip
            if rng.random() < product.return_rate:
                back = {**sold, "Дата продажи": min(day + timedelta(days=rng.randint(1, 5)), end)}
                rows.append({
                    **back, **price, "Тип документа": "Возврат", "Обоснование для оплаты": "Возврат", "Кол-во": 1,
                    "Вайлдберриз реализовал Товар (Пр)": _money(with_discount * 0.9),
                    "К перечислению Продавцу за реализованный Товар": _money(with_discount * (100 - product.kvv) / 100),
                })  # fmt: skip
                rows.append({
                    **back, "Обоснование для оплаты": "Логистика", "Количество возврата": 1,
                    "Услуги по доставке товара покупателю": 50.0,
                    "Виды логистики, штрафов и доплат": "От клиента при возврате",
                })  # fmt: skip
    rows.append({"Дата продажи": end, "Обоснование для оплаты": "Хранение", "Хранение": _money(2450.3 + 180 * week)})
    rows.append({
        "Дата продажи": end, "Обоснование для оплаты": "Удержание", "Удержания": 3000.0,
        "Виды логистики, штрафов и доплат": "Оказание услуг «ВБ.Продвижение»",
    })  # fmt: skip
    rows.append({"Дата продажи": end, "Обоснование для оплаты": "Платная приемка", "Платная приемка": 450.0})
    plaid, bedding, pillowcases = PRODUCTS[0], PRODUCTS[1], PRODUCTS[2]
    if week == 0:
        rows.append({
            "Артикул поставщика": plaid.article, "Название": plaid.name, "Дата продажи": end,
            "Обоснование для оплаты": "Штраф", "Общая сумма штрафов": 1000.0,
            "Виды логистики, штрафов и доплат": "Занижение фактических габаритов упаковки",
        })  # fmt: skip
    else:
        rows.append({
            "Артикул поставщика": bedding.article, "Название": bedding.name, "Дата продажи": end,
            "Тип документа": "Продажа", "Обоснование для оплаты": "Оплата брака", "Кол-во": 1,
            "К перечислению Продавцу за реализованный Товар": 980.0,
        })  # fmt: skip
        rows.append({
            "Артикул поставщика": pillowcases.article, "Название": pillowcases.name, "Дата продажи": end,
            "Тип документа": "Продажа", "Обоснование для оплаты": "Коррекция продаж",
            "К перечислению Продавцу за реализованный Товар": 350.0,
        })  # fmt: skip
    rows.sort(key=lambda row: str(row["Дата продажи"]))  # ISO-даты сортируются как строки
    for number, row in enumerate(rows, start=1):
        row["№"] = number
        row["Номер поставки"] = f"{27_000_000 + week * 10 + number % 3}"
        row["Srid"] = f"d.{rng.getrandbits(48):012x}"
    return rows


def _ozon_rows(rng: random.Random) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start, end = OZON_MONTH
    posting = 70_000_000
    for index, product in enumerate(PRODUCTS):
        item = {
            "SKU": 1_500_000_000 + index * 7919,
            "Артикул": product.article,
            "Название товара или услуги": product.name,
        }
        for _ in range(rng.randint(round(product.ozon_month * 0.8), round(product.ozon_month * 1.2))):
            posting += rng.randint(1, 9)
            quantity = 2 if rng.random() < 0.1 else 1
            day = start + timedelta(days=rng.randrange(31))
            shipment = {
                **item, "Дата начисления": day, "Номер отправления или идентификатор услуги": f"{posting}-0001-1",
                "Дата принятия заказа в обработку или оказания услуги": day - timedelta(days=2),
                "Склад отгрузки": "Электроугли",
            }  # fmt: skip
            revenue = _money(product.ozon_price * quantity)
            parts = {
                "Комиссия за продажу": -_money(revenue * product.ozon_commission / 100),
                PROCESSING: -20.0,
                LAST_MILE: -min(_money(revenue * 0.055), 500.0),
                "Логистика": -_money(45 + 15 * quantity),
            }
            rows.append({
                **shipment, "Тип начисления": "Доставка покупателю", "Количество": quantity,
                "За продажу или возврат до вычета комиссий и услуг": revenue,
                "Ставка комиссии": product.ozon_commission, **parts,
                "Индекс локализации": 1.0, "Итого": _money(revenue + sum(parts.values())),
            })  # fmt: skip
            rows.append({**shipment, "Тип начисления": "Оплата эквайринга", "Итого": -_money(revenue * 0.015)})
            if rng.random() < product.return_rate:
                back = _money(product.ozon_price)
                refund = {
                    "Комиссия за продажу": _money(back * product.ozon_commission / 100),
                    "Обратная логистика": -60.0,
                    "Обработка возврата": -25.0,
                }
                rows.append({
                    **shipment, "Дата начисления": min(day + timedelta(days=rng.randint(3, 10)), end),
                    "Тип начисления": "Получение возврата, отмены, невыкупа от покупателя", "Количество": 1,
                    "За продажу или возврат до вычета комиссий и услуг": -back,
                    "Ставка комиссии": product.ozon_commission, **refund, "Итого": _money(-back + sum(refund.values())),
                })  # fmt: skip
    for number, (kind, amount) in enumerate(
        (
            ("Услуга размещения товаров на складе", -1850.4),
            ("Услуга продвижения Трафареты", -2500.0),
            ("Корректировка стоимости услуги", 120.0),
        ),
        start=1,
    ):
        rows.append({
            "Дата начисления": end, "Тип начисления": kind, "Итого": amount,
            "Номер отправления или идентификатор услуги": f"service-{number}",
        })  # fmt: skip
    rows.sort(key=lambda row: str(row["Дата начисления"]))
    for number, row in enumerate(rows, start=1):
        row["ID начисления"] = 9_000_000 + number
    totals: dict[str, object] = {"ID начисления": "Итого"}  # строка итогов: «Тип начисления» пустой
    for header in OZON_MONEY:
        values = [row.get(header) for row in rows]
        totals[header] = _money(sum(float(value) for value in values if isinstance(value, int | float)))
    rows.append(totals)
    return rows


def _write(
    path: Path,
    headers: Sequence[str],
    rows: Sequence[Mapping[str, object]],
    text_headers: frozenset[str],
    title: Sequence[Sequence[object]] = (),
) -> Path:
    workbook = Workbook()
    sheet = workbook.create_sheet("Отчёт", 0)
    del workbook["Sheet"]
    for line in title:
        sheet.append(list(line))
    sheet.append(list(headers))
    for row in rows:
        sheet.append([row.get(header, "" if header in text_headers else 0) for header in headers])
    workbook.save(path)
    return path


def write_demo(folder: Path, seed: int = 2026) -> DemoFiles:
    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    wb = tuple(
        _write(folder / f"wb-детализация-{start:%Y-%m-%d}.xlsx", WB_HEADERS, _wb_rows(start, week, rng), WB_TEXT)
        for week, start in enumerate(WB_WEEKS)
    )
    first, last = OZON_MONTH
    ozon = _write(
        folder / f"ozon-начисления-{first:%Y-%m}.xlsx",
        OZON_HEADERS,
        _ozon_rows(rng),
        OZON_TEXT,
        title=(("Отчёт о начислениях",), (f"Период: {first:%d.%m.%Y} – {last:%d.%m.%Y}",), ()),
    )
    costs = folder / "себестоимость.csv"
    save_costs(
        costs,
        {p.article: to_kopecks(p.cost) for p in PRODUCTS if p.cost is not None},
        {p.article: p.name for p in PRODUCTS},
    )
    return DemoFiles(wb, (ozon,), costs)
