import os
import plistlib
import subprocess
import sys

import pytest
from PySide6.QtGui import QIcon, QImage

from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from py_spread.__main__ import ICON, FileOpener
from py_spread.storage import SheetData, save_sheet
from py_spread.window import MainWindow
from py_spread.macapp import APP_NAME, set_app_name

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, os.pardir, "scripts")


def test_icon(app):
    image = QImage(ICON)
    assert image.width() == image.height() == 1024
    assert image.pixelColor(512, 512).alpha() == 255 and image.pixelColor(10, 10).alpha() == 0  # a rounded tile
    assert not QIcon(ICON).isNull()
    assert os.path.exists(os.path.join(os.path.dirname(ICON), "ezsheet.icns"))  # for the app bundle


def test_name():
    assert APP_NAME == "EZ Sheet"
    assert set_app_name() is (sys.platform == "darwin")  # (nothing to do off a Mac)


def test_app_bundle(tmp_path):
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "make_app.py"), str(tmp_path), "--no-register"],
                   check=True, capture_output=True)  # (not registered: it's a test's, and goes)
    contents = tmp_path / "EZ Sheet.app" / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    assert info["CFBundleName"] == info["CFBundleDisplayName"] == "EZ Sheet"
    assert info["CFBundleIconFile"] == "ezsheet" and (contents / "Resources" / "ezsheet.icns").exists()
    launcher = contents / "MacOS" / info["CFBundleExecutable"]
    assert os.access(launcher, os.X_OK)
    text = launcher.read_text()
    assert text.startswith("#!/bin/sh\n") and '-m py_spread "$@"' in text and ".venv/bin/python" in text
    [document] = info["CFBundleDocumentTypes"]  # .ezs sheets: this app's to open
    assert document["CFBundleTypeExtensions"] == ["ezs"] and document["LSHandlerRank"] == "Owner"
    [sheet_type] = info["UTExportedTypeDeclarations"]
    assert document["LSItemContentTypes"] == [sheet_type["UTTypeIdentifier"]]
    assert sheet_type["UTTypeTagSpecification"]["public.filename-extension"] == ["ezs"]


# --- Opening a sheet the Finder gives the app ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def sheet(tmp_path, name, text) -> str:
    path = str(tmp_path / name)
    save_sheet(path, SheetData(rows=10, cols=5, cells={(0, 0): text}))
    return path


def test_file_open_event_opens_the_sheet(window, tmp_path, app):
    path = sheet(tmp_path, "budget.ezs", "from the Finder")
    opener = FileOpener(window)
    app.installEventFilter(opener)
    try:
        QApplication.sendEvent(app, QFileOpenEvent(path))
    finally:
        app.removeEventFilter(opener)
    assert window.file_path == path and window.model.get_cell(0, 0) == "from the Finder"


def test_open_document_asks_to_save_changes_first(window, tmp_path, dialogs):
    window.model.set_cell(0, 0, "unsaved")
    window.setWindowModified(True)
    dialogs.save_answer = QMessageBox.Cancel
    assert not window.open_document(sheet(tmp_path, "other.ezs", "other"))
    assert window.model.get_cell(0, 0) == "unsaved" and dialogs.save_prompts == 1
    dialogs.save_answer = QMessageBox.Discard
    assert window.open_document(sheet(tmp_path, "other.ezs", "other"))
    assert window.model.get_cell(0, 0) == "other"


def test_open_document_already_open(window, tmp_path, dialogs):
    path = sheet(tmp_path, "budget.ezs", "saved")
    window.open_document(path)
    window.model.set_cell(0, 0, "changed")  # not saved yet: not opened again, nor asked about
    window.setWindowModified(True)
    assert window.open_document(path) and window.model.get_cell(0, 0) == "changed" and dialogs.save_prompts == 0
