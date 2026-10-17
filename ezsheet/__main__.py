import argparse
import os
import sys

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .macapp import APP_NAME, set_app_name
from .window import MainWindow

ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "ezsheet.png")


class FileOpener(QObject):
    """Opens the sheets the Mac asks the app to (a .ezs double-clicked in
    the Finder, or dropped on the app): they come as file-open events, not
    on the command line."""

    def __init__(self, window):
        super().__init__()
        self.window = window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.FileOpen:
            path = event.file()
            if path:
                self.window.open_document(path)
            return True
        return super().eventFilter(obj, event)


def main() -> int:
    parser = argparse.ArgumentParser(prog="ezsheet", description="A Python spreadsheet.")
    parser.add_argument("file", nargs="?", help="a .ezs file to open, or to create when first saved")
    args = parser.parse_args()

    set_app_name()  # what the menu bar and Dock call it: first, before AppKit reads it
    app = QApplication(sys.argv)
    app.setApplicationName("EzSheet")  # (where its settings are kept: unchanged)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(QIcon(ICON))  # the Dock's icon, too
    window = MainWindow()
    opener = FileOpener(window)
    app.installEventFilter(opener)
    window.show()
    if args.file:
        window.open_or_create(args.file)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
