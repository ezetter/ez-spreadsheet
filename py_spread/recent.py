"""File > Open Recent: the sheets most recently opened or saved, newest
first, kept in the app's preferences (not in any sheet)."""

import os

from . import appearance

MAX_RECENT = 10
SETTINGS_KEY = "recent_files"


def recent_files() -> list[str]:
    value = appearance.settings().value(SETTINGS_KEY)
    if isinstance(value, str):  # a one-item list can come back as just the item
        value = [value]
    if not isinstance(value, list):
        return []
    return [path for path in value if isinstance(path, str) and path][:MAX_RECENT]


def add_recent_file(path: str) -> None:
    """Put a sheet at the top of the list (moving it there if it's already in it)."""
    path = os.path.abspath(path)
    _save([path, *(other for other in recent_files() if other != path)])


def remove_recent_file(path: str) -> None:
    _save([other for other in recent_files() if other != path])


def clear_recent_files() -> None:
    _save([])


def _save(paths: list[str]) -> None:
    settings = appearance.settings()
    if paths:
        settings.setValue(SETTINGS_KEY, paths[:MAX_RECENT])
    else:
        settings.remove(SETTINGS_KEY)


def menu_labels(paths: list[str]) -> list[str]:
    """What the menu shows for each sheet: its file name, followed by its
    folder when another sheet in the list has the same name."""
    names = [os.path.basename(path) for path in paths]
    home = os.path.expanduser("~")
    labels = []
    for path, name in zip(paths, names):
        if names.count(name) > 1:
            folder = os.path.dirname(path)
            if folder == home or folder.startswith(home + os.sep):
                folder = "~" + folder[len(home):]
            name = f"{name} — {folder}"
        labels.append(name)
    return labels
