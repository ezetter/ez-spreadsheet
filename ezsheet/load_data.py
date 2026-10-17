"""Notebook > Load Data to Sheet: finding the pandas DataFrames in the
notebook's Python, and putting one's data in the sheet; and what's in their
columns, for charting them.

The questions run quietly in the kernel (see KernelRunner.evaluate), using
the helpers below, and come back as JSON. Column labels make the first row;
an index that means something (it has a name, as from groupby, or isn't
just row numbers, as from describe) makes the first columns. Numbers stay
numbers, missing values are empty cells, and anything else is its text.
"""

import ast
import json

from .notebook import FrameData

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


def _ezsheet_columns(names):
    """{name: [[label, numbers, text, missing, whole], ...] for each column,
    or why it can't be charted} for some DataFrames."""
    import json, numbers, sys
    pd = sys.modules["pandas"]
    found = {}
    for name in names:
        frame = globals().get(name)
        if not isinstance(frame, pd.DataFrame):
            found[name] = "It's no longer in the notebook's Python."
            continue
        if not all(isinstance(label, str) for label in frame.columns):
            found[name] = "Its column names aren't all text."
            continue
        if frame.columns.duplicated().any():
            found[name] = "Two of its columns have the same name."
            continue
        columns = []
        for label in frame.columns:
            column = frame[label]
            values = column.dropna()
            if pd.api.types.is_bool_dtype(column.dtype):
                has_numbers = has_text = False
                whole = True
            elif pd.api.types.is_numeric_dtype(column.dtype):
                has_numbers, has_text = len(values) > 0, False
                whole = bool((values % 1 == 0).all())
            else:
                numbers_in = [value for value in values
                              if isinstance(value, numbers.Real) and not isinstance(value, bool)]
                has_numbers, has_text = bool(numbers_in), any(isinstance(value, str) for value in values)
                whole = all(float(value).is_integer() for value in numbers_in)
            columns.append([label, has_numbers, has_text, bool(column.isna().any()), whole])
        found[name] = columns
    return json.dumps(found)
'''


def frames_request() -> tuple[str, str]:
    """(code, expression) asking for the notebook's DataFrames."""
    return KERNEL_HELPERS, "_ezsheet_frames()"


def data_request(name: str) -> tuple[str, str]:
    """(code, expression) asking for a DataFrame's data."""
    return KERNEL_HELPERS, f"_ezsheet_frame({name!r})"


def columns_request(names) -> tuple[str, str]:
    """(code, expression) asking what's in some DataFrames' columns."""
    return KERNEL_HELPERS, f"_ezsheet_columns({list(names)!r})"


def frame_columns(text: str) -> dict[str, FrameData | str]:
    """From _ezsheet_columns(): for each DataFrame, a stand-in for its data,
    a few values per column showing what's in it (numbers, whole or not;
    text; missing values), which is all a chart's code needs; or why it
    can't be charted."""
    found = {}
    for name, columns in answer(text).items():
        if isinstance(columns, str):
            found[name] = columns
            continue
        labels, values = [], []
        for label, numbers, text_in, missing, whole in columns:
            labels.append(label)
            values.append(([1 if whole else 1.5] if numbers else []) + (["text"] if text_in else [])
                          + ([None] if missing else []))
        found[name] = FrameData(labels, values)
    return found


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

