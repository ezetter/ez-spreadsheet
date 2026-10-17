import argparse
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .macapp import APP_NAME, set_app_name
from .window import MainWindow

ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "ezsheet.png")


def main() -> int:
    parser = argparse.ArgumentParser(prog="py_spread", description="A Python spreadsheet.")
    parser.add_argument("file", nargs="?", help="a .ezs file to open, or to create when first saved")
    args = parser.parse_args()

    set_app_name()  # what the menu bar and Dock call it: first, before AppKit reads it
    app = QApplication(sys.argv)
    app.setApplicationName("EzSheet")  # (where its settings are kept: unchanged)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(QIcon(ICON))  # the Dock's icon, too
    window = MainWindow()
    window.show()
    if args.file:
        window.open_or_create(args.file)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
