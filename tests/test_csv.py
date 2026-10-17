import pytest

from ezsheet.csvfile import read_csv, write_csv
from ezsheet.storage import SheetFileError
from ezsheet.window import MainWindow


def write_bytes(tmp_path, data, name="data.csv"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


# --- Files ---

def test_round_trip_with_quoting(tmp_path):
    rows = [["name", "note"], ["Smith, J.", 'said "hi"'], ["line\nbreak", ""], ["ünïcode ✓", "3.5"]]
    path = str(tmp_path / "x.csv")
    write_csv(path, rows)
    assert read_csv(path) == rows


def test_written_format(tmp_path):
    path = tmp_path / "x.csv"
    write_csv(str(path), [["a", "b,c"], ["1", ""]])
    assert path.read_text(encoding="utf-8") == 'a,"b,c"\n1,\n'


@pytest.mark.parametrize("data, expected", [
    (b"a,b\n1,2\n", [["a", "b"], ["1", "2"]]),
    (b"a,b\r\n1,2\r\n", [["a", "b"], ["1", "2"]]),                 # Windows line endings
    (b"\xef\xbb\xbfa,b\n1,2\n", [["a", "b"], ["1", "2"]]),         # Excel's UTF-8 byte order mark
    (b"caf\xe9,1\n", [["café", "1"]]),                             # older Excel: Windows encoding
    (b"a;b\n1,5;2,5\n", [["a", "b"], ["1,5", "2,5"]]),             # semicolons
    (b"a\tb\n1\t2\n", [["a", "b"], ["1", "2"]]),                   # tabs
    (b"1\n2\n3\n", [["1"], ["2"], ["3"]]),                         # one column
    (b"a,b\n1,2\n\n\n", [["a", "b"], ["1", "2"]]),                 # trailing blank lines
    (b"a,b,c\n1\n", [["a", "b", "c"], ["1"]]),                     # ragged
    (b"", []),
])
def test_read_csv(tmp_path, data, expected):
    assert read_csv(write_bytes(tmp_path, data)) == expected


def test_read_missing_file(tmp_path):
    with pytest.raises(SheetFileError):
        read_csv(str(tmp_path / "missing.csv"))


def test_read_binary_file(tmp_path):
    with pytest.raises(SheetFileError):
        read_csv(write_bytes(tmp_path, bytes(range(128, 256)) * 4))


# --- In the window ---

@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    yield window
    window.setWindowModified(False)
    window.close()


def test_menu_items(window):
    file_menu = [m for m in window.menuBar().actions() if m.text() == "File"][0].menu()
    names = [a.text() for a in file_menu.actions() if a.text()]
    assert names[-2:] == ["Import CSV…", "Export CSV…"]


def test_export_writes_displayed_values(window, tmp_path):
    model = window.model
    model.set_cells({(0, 0): "Item", (0, 1): "Qty", (1, 0): "bolt", (1, 1): "4",
                     (2, 0): "nut", (2, 1): "=B2*2.5", (3, 1): "=1/0"})
    path = tmp_path / "out.csv"
    assert window.export_csv_to(str(path))
    assert path.read_text(encoding="utf-8") == "Item,Qty\nbolt,4\nnut,10\n,#DIV/0!\n"
    assert "Exported 4 rows × 2 columns" in window.statusBar().currentMessage()


def test_export_keeps_positions_from_a1(window, tmp_path):
    window.model.set_cell(1, 2, "x")
    path = tmp_path / "out.csv"
    window.export_csv_to(str(path))
    assert path.read_text(encoding="utf-8") == ",,\n,,x\n"


def test_export_does_not_change_document(window, tmp_path):
    window.model.set_cell(0, 0, "x")
    window.export_csv_to(str(tmp_path / "out.csv"))
    assert window.file_path is None
    assert window.isWindowModified()


def test_export_empty_sheet(window, tmp_path):
    path = tmp_path / "out.csv"
    assert not window.export_csv_to(str(path))
    assert not path.exists()
    assert "empty" in window.statusBar().currentMessage()


def test_export_failure_reports_error(window, tmp_path, dialogs):
    window.model.set_cell(0, 0, "x")
    assert not window.export_csv_to(str(tmp_path / "no-such-folder" / "out.csv"))
    assert dialogs.errors


def test_import_at_selected_cell(window, tmp_path):
    path = write_bytes(tmp_path, b"a,b\n1,2\n3\n")
    window.view.select_range(4, 2, 6, 3)
    assert window.import_csv_from(path)
    model = window.model
    assert [[model.get_cell(r, c) for c in (2, 3)] for r in (4, 5, 6)] == [["a", "b"], ["1", "2"], ["3", ""]]
    assert model.value(5, 2) == 1.0  # numbers are numbers
    selected = {(i.row(), i.column()) for i in window.view.selectedIndexes()}
    assert selected == {(r, c) for r in (4, 5, 6) for c in (2, 3)}
    assert "Imported 3 rows × 2 columns from data.csv at C5" in window.statusBar().currentMessage()


def test_import_clears_ragged_gaps(window, tmp_path):
    window.model.set_cell(1, 1, "old")
    window.import_csv_from(write_bytes(tmp_path, b"a,b\n1\n"))
    assert window.model.get_cell(1, 1) == ""


def test_import_is_one_undo_step(window, tmp_path):
    window.model.set_cell(0, 0, "before")
    window.import_csv_from(write_bytes(tmp_path, b"x,y\n1,2\n"))
    assert window.undo_action.text() == "Undo Import CSV"
    window.undo_action.trigger()
    assert window.model.sheet_data().cells == {(0, 0): "before"}


def test_import_grows_sheet(window, tmp_path):
    data = b"\n".join(b",".join(b"%d" % (r * 100 + c) for c in range(60)) for r in range(1200)) + b"\n"
    window.import_csv_from(write_bytes(tmp_path, data))
    model = window.model
    assert (model.rowCount(), model.columnCount()) == (1200, 60)
    assert model.get_cell(1199, 59) == str(1199 * 100 + 59)


def test_import_then_save_keeps_bigger_size(window, tmp_path):
    from ezsheet.storage import load_sheet
    data = b"\n".join(b"x" for _ in range(1500)) + b"\n"
    window.import_csv_from(write_bytes(tmp_path, data))
    sheet_path = str(tmp_path / "big.ezs")
    window.save_to(sheet_path)
    assert load_sheet(sheet_path).rows == 1500


def test_import_bad_file_reports_error(window, tmp_path, dialogs):
    assert not window.import_csv_from(str(tmp_path / "missing.csv"))
    assert dialogs.errors


def test_import_empty_file(window, tmp_path):
    assert not window.import_csv_from(write_bytes(tmp_path, b""))
    assert "empty" in window.statusBar().currentMessage()
    assert not window.undo_action.isEnabled()


def test_round_trip_through_the_window(window, tmp_path):
    window.model.set_cells({(0, 0): "a, b", (0, 1): "=2*3", (1, 0): 'q"uote'})
    path = str(tmp_path / "rt.csv")
    window.export_csv_to(path)
    other = MainWindow()
    other.import_csv_from(path)
    assert other.model.sheet_data().cells == {(0, 0): "a, b", (0, 1): "6", (1, 0): 'q"uote'}
    other.setWindowModified(False)
