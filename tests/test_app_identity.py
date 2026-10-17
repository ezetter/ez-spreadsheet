import os
import plistlib
import subprocess
import sys

import pytest
from PySide6.QtGui import QIcon, QImage

from py_spread.__main__ import ICON
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
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "make_app.py"), str(tmp_path)], check=True,
                   capture_output=True)
    contents = tmp_path / "EZ Sheet.app" / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    assert info["CFBundleName"] == info["CFBundleDisplayName"] == "EZ Sheet"
    assert info["CFBundleIconFile"] == "ezsheet" and (contents / "Resources" / "ezsheet.icns").exists()
    launcher = contents / "MacOS" / info["CFBundleExecutable"]
    assert os.access(launcher, os.X_OK)
    text = launcher.read_text()
    assert text.startswith("#!/bin/sh\n") and '-m py_spread "$@"' in text and ".venv/bin/python" in text
