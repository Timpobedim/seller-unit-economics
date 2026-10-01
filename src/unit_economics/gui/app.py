"""Запуск окна: unit-economics-gui [--demo]."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from unit_economics.gui.window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("PortfolioMaker")
    app.setApplicationName("unit-economics")
    window = MainWindow()
    window.resize(1320, 820)
    window.show()
    if "--demo" in sys.argv[1:]:
        window.load_demo()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
