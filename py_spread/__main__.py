import argparse
import sys

from PySide6.QtWidgets import QApplication

from .window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(prog="py_spread", description="A Python spreadsheet.")
    parser.add_argument("file", nargs="?", help="a .pysheet file to open")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Py-Spread")
    window = MainWindow()
    window.show()
    if args.file:
        window.open_path(args.file)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
