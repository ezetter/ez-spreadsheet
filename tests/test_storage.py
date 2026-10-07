import json
import os
import stat

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QMessageBox

from py_spread.storage import VERSION, SheetData, SheetFileError, load_sheet, save_sheet
from py_spread.window import MainWindow


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def write_json(path, document):
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def test_round_trip(tmp_path):
    path = str(tmp_path / "s.ezs")
    sheet = SheetData(1000, 52, {(0, 0): "Item", (2, 1): "=B2*3", (1, 27): "émoji ✓"})
    save_sheet(path, sheet)
    assert load_sheet(path) == sheet


def test_file_is_readable_json(tmp_path):
    path = tmp_path / "s.ezs"
    save_sheet(str(path), SheetData(10, 5, {(1, 0): "b", (0, 1): "a"}))
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document == {"format": "ezsheet", "version": VERSION, "rows": 10, "columns": 5,
                        "angles": "degrees", "cells": {"B1": "a", "A2": "b"}}
    assert list(document["cells"]) == ["B1", "A2"]  # row by row


def test_failed_save_keeps_old_file(tmp_path, monkeypatch):
    path = tmp_path / "s.ezs"
    save_sheet(str(path), SheetData(10, 5, {(0, 0): "original"}))

    def broken_replace(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("py_spread.storage.os.replace", broken_replace)
    with pytest.raises(SheetFileError):
        save_sheet(str(path), SheetData(10, 5, {(0, 0): "new"}))
    assert load_sheet(str(path)).cells == {(0, 0): "original"}
    assert [p.name for p in tmp_path.iterdir()] == ["s.ezs"]  # no temp file left


def test_save_to_missing_directory(tmp_path):
    with pytest.raises(SheetFileError):
        save_sheet(str(tmp_path / "nope" / "s.ezs"), SheetData(10, 5))


def test_load_grows_sheet_to_fit_cells(tmp_path):
    path = write_json(tmp_path / "s.ezs", {"format": "ezsheet", "version": 1, "rows": 10,
                                               "columns": 5, "cells": {"G20": "x"}})
    sheet = load_sheet(path)
    assert (sheet.rows, sheet.cols) == (20, 7)


@pytest.mark.parametrize("content", [
    "not json",
    json.dumps([1, 2]),
    json.dumps({"format": "other", "version": 1, "rows": 1, "columns": 1, "cells": {}}),
    json.dumps({"format": "ezsheet", "version": 99, "rows": 1, "columns": 1, "cells": {}}),
    json.dumps({"format": "ezsheet", "version": 1, "rows": 0, "columns": 1, "cells": {}}),
    json.dumps({"format": "ezsheet", "version": 1, "rows": True, "columns": 1, "cells": {}}),
    json.dumps({"format": "ezsheet", "version": 1, "rows": 1, "columns": 1, "cells": []}),
    json.dumps({"format": "ezsheet", "version": 1, "rows": 1, "columns": 1, "cells": {"1A": "x"}}),
    json.dumps({"format": "ezsheet", "version": 1, "rows": 1, "columns": 1, "cells": {"A0": "x"}}),
    json.dumps({"format": "ezsheet", "version": 1, "rows": 1, "columns": 1, "cells": {"A1": 5}}),
])
def test_rejects_bad_files(tmp_path, content):
    path = tmp_path / "s.ezs"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SheetFileError):
        load_sheet(str(path))


def test_missing_file(tmp_path):
    with pytest.raises(SheetFileError):
        load_sheet(str(tmp_path / "missing.ezs"))


def test_window_save_and_open(window, tmp_path):
    path = str(tmp_path / "budget.ezs")
    window.model.set_cell(0, 0, "4")
    window.model.set_cell(0, 1, "=A1*2")
    assert window.isWindowModified()
    assert window.save_to(path)
    assert not window.isWindowModified()
    assert window.windowTitle() == "budget.ezs[*] — EzSheet"

    other = MainWindow()
    assert other.open_path(path)
    assert other.model.display_text(0, 1) == "8"
    assert other.file_path == path
    assert not other.isWindowModified()


def test_save_includes_cell_being_edited(window, tmp_path):
    path = str(tmp_path / "s.ezs")
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    QTest.keyClick(window.view, "h")
    editor = window.view.viewport().findChild(QLineEdit)
    QTest.keyClicks(editor, "i")
    assert window.save_to(path)
    assert load_sheet(path).cells == {(0, 0): "hi"}


def test_save_includes_edit_bar_text(window, tmp_path):
    path = str(tmp_path / "s.ezs")
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    window.edit_bar.setFocus()
    QTest.keyClicks(window.edit_bar, "=1+1")
    assert window.save_to(path)
    assert load_sheet(path).cells == {(0, 0): "=1+1"}


def test_open_replaces_sheet_and_resets_cursor(window, tmp_path):
    path = str(tmp_path / "s.ezs")
    save_sheet(path, SheetData(1000, 52, {(0, 0): "loaded"}))
    window.model.set_cell(5, 5, "old")
    window.setWindowModified(False)
    window.view.setCurrentIndex(window.model.index(5, 5))
    assert window.open_path(path)
    assert window.model.sheet_data().cells == {(0, 0): "loaded"}
    assert window.view.currentIndex() == window.model.index(0, 0)
    assert window.edit_bar.text() == "loaded"


def test_open_bad_file_reports_error_and_keeps_sheet(window, tmp_path, dialogs):
    path = tmp_path / "bad.ezs"
    path.write_text("garbage", encoding="utf-8")
    window.model.set_cell(0, 0, "keep")
    assert not window.open_path(str(path))
    assert dialogs.errors and "isn't an EzSheet sheet" in dialogs.errors[0]
    assert window.model.get_cell(0, 0) == "keep"


def test_new_asks_before_discarding(window, dialogs):
    window.model.set_cell(0, 0, "work")
    dialogs.save_answer = QMessageBox.Cancel
    window.new_file()
    assert dialogs.save_prompts == 1
    assert window.model.get_cell(0, 0) == "work"

    dialogs.save_answer = QMessageBox.Discard
    window.new_file()
    assert window.model.sheet_data().cells == {}
    assert window.file_path is None
    assert not window.isWindowModified()


def test_new_without_changes_does_not_ask(window, dialogs):
    window.new_file()
    assert dialogs.save_prompts == 0


def test_close_with_save_answer_saves(window, dialogs, tmp_path):
    path = str(tmp_path / "s.ezs")
    window.save_to(path)
    window.model.set_cell(0, 0, "late edit")
    dialogs.save_answer = QMessageBox.Save
    assert window.close()
    assert load_sheet(path).cells == {(0, 0): "late edit"}


def test_close_cancelled_keeps_window_open(window, dialogs):
    window.model.set_cell(0, 0, "x")
    dialogs.save_answer = QMessageBox.Cancel
    assert not window.close()
    assert window.isVisible()


def test_loading_cancels_pending_cut(window, tmp_path):
    path = str(tmp_path / "s.ezs")
    save_sheet(path, SheetData(1000, 52, {(0, 0): "from file"}))
    window.model.set_cell(0, 0, "cut me")
    window.view.setCurrentIndex(window.model.index(0, 0))
    window.clipboard.cut()
    window.setWindowModified(False)
    window.open_path(path)
    window.view.setCurrentIndex(window.model.index(3, 3))
    window.clipboard.paste()
    assert window.model.get_cell(0, 0) == "from file"  # cut source not cleared in the new sheet


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_new_file_gets_default_permissions(tmp_path):
    path = str(tmp_path / "s.ezs")
    old_umask = os.umask(0o022)
    try:
        save_sheet(path, SheetData(10, 5))
    finally:
        os.umask(old_umask)
    assert mode(path) == 0o644


def test_overwrite_keeps_existing_permissions(tmp_path):
    path = str(tmp_path / "s.ezs")
    save_sheet(path, SheetData(10, 5))
    os.chmod(path, 0o640)
    save_sheet(path, SheetData(10, 5, {(0, 0): "x"}))
    assert mode(path) == 0o640


def test_open_or_create_missing_file_starts_named_sheet(window, tmp_path, dialogs):
    path = tmp_path / "budget.ezs"
    assert window.open_or_create(str(path))
    assert dialogs.errors == []
    assert window.file_path == str(path)
    assert window.windowTitle() == "budget.ezs[*] — EzSheet"
    assert not path.exists()  # nothing is written until saved
    window.model.set_cell(0, 0, "rent")
    assert window.save()  # saves straight to the path, no dialog
    assert load_sheet(str(path)).cells == {(0, 0): "rent"}


def test_open_or_create_makes_relative_path_absolute(window, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    window.open_or_create("budget.ezs")
    assert window.file_path == str(tmp_path / "budget.ezs")


def test_open_or_create_existing_file_opens_it(window, tmp_path):
    path = str(tmp_path / "s.ezs")
    save_sheet(path, SheetData(10, 5, {(0, 0): "there"}))
    assert window.open_or_create(path)
    assert window.model.get_cell(0, 0) == "there"


def test_open_or_create_in_missing_folder_is_an_error(window, tmp_path, dialogs):
    assert not window.open_or_create(str(tmp_path / "no-such-folder" / "s.ezs"))
    assert dialogs.errors
    assert window.file_path is None


def test_the_format_is_ezsheet(tmp_path, app):
    from py_spread.storage import EXTENSION, FORMAT
    from py_spread.window import FILE_FILTER
    assert (EXTENSION, FORMAT) == (".ezs", "ezsheet")
    assert FILE_FILTER == "EzSheet Sheets (*.ezs)"


def test_old_py_spread_files_are_not_supported(tmp_path):
    path = tmp_path / "old.pysheet"
    path.write_text(json.dumps({"format": "py-spread", "version": 6, "rows": 10, "columns": 5, "cells": {}}))
    with pytest.raises(SheetFileError, match="isn't an EzSheet sheet"):
        load_sheet(str(path))


def test_window_title_uses_new_name(window, tmp_path):
    assert window.windowTitle() == "Untitled[*] — EzSheet"
    window.save_to(str(tmp_path / "budget.ezs"))
    assert window.windowTitle() == "budget.ezs[*] — EzSheet"
