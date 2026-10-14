"""Notebook > Load Data to Sheet: finding the pandas DataFrames in the
notebook's Python, and putting one's data in the sheet.

The questions run quietly in the kernel (see KernelRunner.evaluate), using
the helpers below, and come back as JSON. Column labels make the first row;
an index that means something (it has a name, as from groupby, or isn't
just row numbers, as from describe) makes the first columns. Numbers stay
numbers, missing values are empty cells, and anything else is its text.
"""

import ast
import json

MAX_CELLS = 100_000  # bigger DataFrames would make the sheet slow

# Defined in the notebook's Python each time (with underscores, so %who and
# the like leave them out), and run there.
KERNEL_HELPERS = r'''
def _ezsheet_frames():
    """[[name, rows, columns], ...] for the notebook's DataFrames."""
    import json, sys
    pd = sys.modules.get("pandas")
    if pd is None:
        return json.dumps([])
    return json.dumps([[name, *value.shape] for name, value in globals().items()
                       if isinstance(value, pd.DataFrame) and not name.startswith("_")])


def _ezsheet_frame(name):
    """A DataFrame's labels and rows, as JSON the sheet can take."""
    import json, math, numbers, sys
    pd = sys.modules["pandas"]
    frame = globals()[name]
    index = frame.index
    if any(level is not None for level in index.names) or not pd.api.types.is_integer_dtype(index.dtype):
        frame = frame.reset_index(allow_duplicates=True)  # a meaningful index: its own columns

    def label(value):
        if isinstance(value, tuple):  # from MultiIndex columns
            return " ".join(str(part) for part in value if str(part))
        return str(value)

    def cell(value):
        if value is None or type(value).__name__ in ("bool", "bool_"):
            return None if value is None else str(bool(value))
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):  # a list or the like
            pass
        if isinstance(value, numbers.Integral):
            return int(value)
        if isinstance(value, numbers.Real):
            number = float(value)
            return number if math.isfinite(number) else str(number)
        return str(value)

    rows = [[cell(value) for value in row] for row in frame.itertuples(index=False, name=None)]
    return json.dumps({"columns": [label(column) for column in frame.columns], "rows": rows})
'''


def frames_request() -> tuple[str, str]:
    """(code, expression) asking for the notebook's DataFrames."""
    return KERNEL_HELPERS, "_ezsheet_frames()"


def data_request(name: str) -> tuple[str, str]:
    """(code, expression) asking for a DataFrame's data."""
    return KERNEL_HELPERS, f"_ezsheet_frame({name!r})"


def answer(text: str):
    """What a helper returned: the kernel gives its repr, a quoted string of JSON."""
    return json.loads(ast.literal_eval(text))


def frames(text: str) -> list[tuple[str, int, int]]:
    """The (name, rows, columns) of each DataFrame, from _ezsheet_frames()."""
    return [(name, rows, columns) for name, rows, columns in answer(text)]


def too_big(rows: int, columns: int) -> bool:
    return rows * columns > MAX_CELLS


def sheet_writes(data: dict, top: int, left: int) -> dict[tuple[int, int], str]:
    """The text for each cell: the labels in row `top`, then the rows, from
    column `left` on. Missing values clear their cells."""
    writes = {(top, left + c): label for c, label in enumerate(data["columns"])}
    for r, row in enumerate(data["rows"], start=1):
        for c, value in enumerate(row):
            writes[(top + r, left + c)] = _text(value)
    return writes


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    return str(value)


def describe(name: str, rows: int, columns: int) -> str:
    """How the list shows a DataFrame: "df: 3 rows × 2 columns"."""
    return f"{name}: {rows:,} row{'s' if rows != 1 else ''} × {columns} column{'s' if columns != 1 else ''}"

