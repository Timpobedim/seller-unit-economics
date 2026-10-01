"""Командная строка: тот же расчёт без окна — для автоматизации и проверки.

unit-economics report --wb wb-1.xlsx wb-2.xlsx --ozon ozon.xlsx --costs себестоимость.csv -o итог.xlsx
unit-economics demo --out demo
"""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from unit_economics.columns import ReportFormatError
from unit_economics.costs import CostsError, load_costs
from unit_economics.demo import write_demo
from unit_economics.export import ExportError, export_report
from unit_economics.fmt import format_value
from unit_economics.money import MoneyError, parse_decimal, to_kopecks
from unit_economics.ozon import parse_ozon
from unit_economics.pnl import SUMMARY_ROWS, Pnl, Settings, TaxMode, build_pnl
from unit_economics.wb import parse_wb

TAX = {"none": TaxMode.NONE, "usn-income": TaxMode.INCOME, "usn-profit": TaxMode.PROFIT}


def _rate(value: str) -> Decimal:
    try:
        rate = parse_decimal(value)
    except MoneyError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not 0 <= rate <= 100:
        raise argparse.ArgumentTypeError("ставка должна быть от 0 до 100 %")
    return rate


def _amount(value: str) -> int:
    try:
        kopecks = to_kopecks(value)
    except MoneyError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if kopecks < 0:
        raise argparse.ArgumentTypeError("сумма не может быть отрицательной")
    return kopecks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="unit-economics", description="Юнит-экономика по отчётам WB и Ozon")
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="посчитать и сохранить отчёт в Excel")
    report.add_argument("--wb", nargs="+", type=Path, default=[], metavar="ФАЙЛ", help="детализации отчётов WB")
    report.add_argument("--ozon", nargs="+", type=Path, default=[], metavar="ФАЙЛ", help="начисления Ozon")
    report.add_argument("--costs", type=Path, help="себестоимость: CSV или XLSX с колонками «Артикул», «Себестоимость»")
    report.add_argument("--tax", choices=sorted(TAX), default="usn-income", help="налоговый режим")
    report.add_argument("--rate", type=_rate, default=Decimal(6), help="ставка налога, %% (по умолчанию 6)")
    report.add_argument("--ads-wb", type=_amount, default=0, help="реклама на WB за период, ₽")
    report.add_argument("--ads-ozon", type=_amount, default=0, help="реклама на Ozon за период, ₽")
    report.add_argument("-o", "--out", type=Path, default=Path("юнит-экономика.xlsx"), help="куда сохранить отчёт")
    sample = commands.add_parser("demo", help="создать демо-отчёты и посчитать по ним")
    sample.add_argument("--out", type=Path, default=Path("demo"), help="папка для демо-файлов")
    return parser


def print_summary(pnl: Pnl) -> None:
    width = max(len(title) for title, _, _ in SUMMARY_ROWS) + 2
    print(pnl.title)
    print(" " * width + "".join(totals.platform.rjust(20) for totals in pnl.totals))
    for title, getter, kind in SUMMARY_ROWS:
        print(title.ljust(width) + "".join(format_value(getter(totals), kind).rjust(20) for totals in pnl.totals))
    if pnl.problems:
        print("\nЧто проверить:")
        for problem in pnl.problems:
            print(f"  • {problem}")


def calculate(wb: Sequence[Path], ozon: Sequence[Path], costs: Path | None, settings: Settings) -> Pnl:
    reports = [parse_wb(path) for path in wb] + [parse_ozon(path) for path in ozon]
    return build_pnl(reports, load_costs(costs) if costs else {}, settings)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "demo":
        files = write_demo(args.out)
        pnl = calculate(files.wb, files.ozon, files.costs, Settings())
        out = args.out / "юнит-экономика.xlsx"
    else:
        if not args.wb and not args.ozon:
            parser.error("укажите хотя бы один отчёт: --wb и/или --ozon")
        settings = Settings(TAX[args.tax], args.rate, {"WB": args.ads_wb, "Ozon": args.ads_ozon})
        try:
            pnl = calculate(args.wb, args.ozon, args.costs, settings)
        except (ReportFormatError, CostsError) as exc:
            print(exc, file=sys.stderr)
            return 2
        out = args.out
    print_summary(pnl)
    try:
        export_report(out, pnl)
    except ExportError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"\nОтчёт: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
