"""Reading and writing CSV files."""

import csv
import io

from .storage import SheetFileError, write_text_atomically

# Delimiters to detect on import: comma, plus the semicolon some locales use
# (where the comma is the decimal point) and tab.
DELIMITERS = ",;\t"
SNIFF_SAMPLE = 64 * 1024


def read_csv(path: str) -> list[list[str]]:
    """The rows of a CSV file, each a list of field strings."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise SheetFileError(f"Couldn't open {path}: {e.strerror or e}") from e
    text = _decode(data, path)
    if not text.strip():
        return []
    try:
        dialect = csv.Sniffer().sniff(text[:SNIFF_SAMPLE], delimiters=DELIMITERS)
    except csv.Error:
        dialect = csv.excel  # one column, or too little to tell: plain commas
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), dialect))
    except csv.Error as e:
        raise SheetFileError(f"{path} couldn't be read as CSV: {e}") from e
    while rows and not any(rows[-1]):
        rows.pop()  # trailing blank lines
    return rows


def _decode(data: bytes, path: str) -> str:
    # UTF-8 (with or without the byte order mark Excel adds), else the
    # Windows encoding that older Excel versions write.
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise SheetFileError(f"{path} isn't a text file in a supported encoding (UTF-8 or Windows).")


def write_csv(path: str, rows: list[list[str]]) -> None:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    write_text_atomically(path, buffer.getvalue())
