"""Build EZ Sheet.app, so the Dock, the Finder, and the menu bar show EZ
Sheet's name and icon, and double-clicking a .ezs sheet opens it: a Mac app
bundle that runs this project's EZ Sheet (with its .venv's Python), in dist/
by default. It's registered with the Mac as the app for .ezs files.

    .venv/bin/python scripts/make_app.py              # dist/EZ Sheet.app
    .venv/bin/python scripts/make_app.py ~/Applications

Drag it to the Dock, or open it from the Finder. It runs the project where it
is, so build it again if the project moves. (scripts/make_icon.py draws the
icon it uses.)
"""

import os
import plistlib
import shutil
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.normpath(os.path.join(HERE, os.pardir))
NAME = "EZ Sheet"
ICON = os.path.join(PROJECT, "py_spread", "resources", "ezsheet.icns")
SHEET_TYPE = "com.ezsheet.sheet"  # .ezs files' type, as the app declares it
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/"
              "Support/lsregister")


def build(folder: str) -> str:
    app = os.path.join(folder, f"{NAME}.app")
    if os.path.exists(app):
        shutil.rmtree(app)
    contents = os.path.join(app, "Contents")
    os.makedirs(os.path.join(contents, "MacOS"))
    os.makedirs(os.path.join(contents, "Resources"))
    with open(os.path.join(contents, "Info.plist"), "wb") as f:
        plistlib.dump({
            "CFBundleName": NAME,
            "CFBundleDisplayName": NAME,
            "CFBundleIdentifier": "com.ezsheet.EZSheet",
            "CFBundleExecutable": NAME,
            "CFBundleIconFile": "ezsheet",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0",
            "CFBundleVersion": "1",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # .ezs sheets: a type of their own (JSON inside), which this app opens and saves.
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": SHEET_TYPE,
                "UTTypeDescription": "EZ Sheet sheet",
                "UTTypeConformsTo": ["public.data", "public.content"],
                "UTTypeIconFile": "ezsheet",
                "UTTypeTagSpecification": {"public.filename-extension": ["ezs"]},
            }],
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "EZ Sheet sheet",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": [SHEET_TYPE],
                "CFBundleTypeExtensions": ["ezs"],
                "CFBundleTypeIconFile": "ezsheet",
            }],
        }, f)
    shutil.copy(ICON, os.path.join(contents, "Resources", "ezsheet.icns"))
    python = os.path.join(PROJECT, ".venv", "bin", "python")
    launcher = os.path.join(contents, "MacOS", NAME)
    with open(launcher, "w") as f:
        f.write("#!/bin/sh\n"
                f"# Runs EZ Sheet from {PROJECT}.\n"
                f"cd {_quoted(PROJECT)} || exit 1\n"
                f'exec {_quoted(python)} -m py_spread "$@"\n')
    os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return app


def register(app: str) -> bool:
    """Tell the Mac about the app (and so its .ezs files) now, not when the
    Finder next notices it; whether it could."""
    if not os.path.exists(LSREGISTER):
        return False
    return subprocess.run([LSREGISTER, "-f", app], capture_output=True).returncode == 0


def _quoted(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


def main() -> int:
    folders = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    folder = os.path.expanduser(folders[0]) if folders else os.path.join(PROJECT, "dist")
    os.makedirs(folder, exist_ok=True)
    app = build(folder)
    print("built", app)
    if "--no-register" not in sys.argv and register(app):
        print("registered it as the app for .ezs files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
