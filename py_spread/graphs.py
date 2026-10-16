"""The notebook's charts (graphs, in the code's names): finding cells that
draw a Seaborn chart (one sns.relplot, sns.catplot, or sns.lmplot call),
reading what they draw, and changing it, for the Chart dialog.

Changing a graph's type or marker touches only kind=, marker= (lmplot's
markers=), and which of relplot, catplot, and lmplot draws it, so anything
else changed by hand in its cell stays. Changing its columns writes the cell afresh, from the data in the
DataFrame's own cell. Renaming its DataFrame renames it in that cell, and
in the cells after it that use it.
"""

import ast
import re
from dataclasses import dataclass, field

from .notebook import (
    FRAME_COMMENT,
    GRAPH_KINDS,
    OTHER_KINDS,
    REGRESSION,
    FrameData,
    GraphColumns,
    GraphError,
    dataframe_parts,
    marker_keyword,
    plot_function,
)

FUNCTION_KINDS = {"relplot": ("line", "scatter"), "catplot": ("strip", "swarm"), "lmplot": ("reg",)}  # here
DEFAULT_KINDS = {"relplot": "scatter", "catplot": "strip", "lmplot": "reg"}  # their kind when none is given
_FRAME_COMMENT = re.compile(r"^#\s*(\w+) as a (?:chart|graph)\b", re.M)  # as graph_code writes it (or did)
_OTHER_KIND = re.compile(r"[ \t]*#\s*or\s*(['\"])(line|scatter|strip|swarm)\1[^\n]*")  # "# or 'scatter'"
_NOT_LITERAL = object()


@dataclass
class GraphCell:
    cell_id: str
    kind: str  # one of GRAPH_KINDS
    marker: str | None
    frame: str | None = None  # the DataFrame it graphs, if known
    x_label: str | None = None
    y_labels: list[str] = field(default_factory=list)
    data: FrameData | None = None  # the DataFrame's data, from its cell, if found
    columns: GraphColumns | None = None  # what can go across and up, given the data
    hue: str | None = None  # the column coloring its points, if any
    y_categories: bool = False  # orient='h': sideways, with the y column as categories
    col: str | None = None  # the column splitting it into panels, one for each of its values, if any
    frame_cell: str | None = None  # the id of the cell making its DataFrame, if found

    @property
    def renamable(self) -> bool:
        """Whether its DataFrame can be renamed: its cell is found, written as EzSheet writes it."""
        return self.frame_cell is not None and self.data is not None

    @property
    def title(self) -> str:
        """What it graphs: "Sales and Cost against Month"."""
        if not self.x_label or not self.y_labels:
            return f"a chart of {self.frame}" if self.frame else "a chart"
        ys = self.y_labels
        if len(ys) == 1:
            series = ys[0]
        elif len(ys) == 2:
            series = f"{ys[0]} and {ys[1]}"
        else:
            series = f"{', '.join(ys[:-1])}, and {ys[-1]}"
        return f"{series} against {self.x_label}"


def find_graphs(notebook) -> list[GraphCell]:
    """The notebook's graph cells whose type and marker can be changed, top
    to bottom, each with its DataFrame's data if its cell is found."""
    graphs = []
    for cell in notebook.cells:
        graph = read_graph(cell.source)
        if graph is not None:
            graph.cell_id = cell.id
            made = frame_cell(notebook, cell.id, graph.frame)
            graph.frame_cell = made
            graph.data = frame_data(notebook.cell(made).source, graph.frame) if made else None
            if graph.data is not None:
                try:
                    graph.columns = GraphColumns.of(graph.data)
                except GraphError:
                    graph.data = None
            graphs.append(graph)
    return graphs


def read_graph(source: str) -> GraphCell | None:
    """The graph a cell's code draws, or None if it doesn't draw exactly one
    relplot, catplot, or lmplot graph of a kind the Chart dialog has, with a
    plain marker."""
    found = _plot_call(source)
    if found is None:
        return None
    tree, call = found
    function = call.func.attr
    keywords = {k.arg: k.value for k in call.keywords if k.arg}
    kind = _literal(keywords["kind"]) if "kind" in keywords else DEFAULT_KINDS[function]
    if kind not in FUNCTION_KINDS[function]:
        return None
    key = marker_keyword(kind)
    marker = _literal(keywords[key]) if key in keywords else None
    if not (marker is None or isinstance(marker, str) and marker):  # (not a list of them, one per hue)
        return None
    graph = GraphCell("", kind, marker, frame=_frame_name(source, tree))
    x, y = _literal(keywords.get("x")), _literal(keywords.get("y"))
    graph.x_label = x if isinstance(x, str) else None
    melted = _melted_columns(tree)
    if "hue" in keywords and melted:  # a series for each of several y columns, melted into one
        graph.y_labels = melted
    else:
        graph.y_labels = [y] if isinstance(y, str) else []
        hue = _literal(keywords.get("hue"))
        graph.hue = hue if isinstance(hue, str) else None
    graph.y_categories = _literal(keywords.get("orient")) in ("h", "y")
    col = _literal(keywords.get("col"))
    graph.col = col if isinstance(col, str) else None
    return graph


def change_graph(source: str, kind: str, marker: str | None) -> str:
    """The cell's code with its graph's kind and marker changed (no marker:
    marker= is taken out), switching between relplot, catplot, and lmplot as
    the kind needs. lmplot has no kind=, and calls its marker markers=."""
    if kind not in GRAPH_KINDS:  # (for a hue or new columns, the cell is written afresh)
        raise ValueError(f"kind must be one of {', '.join(GRAPH_KINDS)}, not {kind!r}")
    if read_graph(source) is None:
        raise ValueError("the code doesn't draw a chart that can be changed")
    _tree, call = _plot_call(source)
    at = _Positions(source)
    keywords = {k.arg: k for k in call.keywords if k.arg}
    edits = []  # (start, end, new text), applied from the end backward

    function = plot_function(kind)
    if call.func.attr != function:
        end = at(call.func.end_lineno, call.func.end_col_offset)
        edits.append((end - len(call.func.attr), end, function))

    other = OTHER_KINDS.get(kind, "")
    if kind in REGRESSION:
        if "kind" in keywords:  # lmplot has none: out it goes, with "# or 'line'"
            start, end = _keyword_span(source, at, keywords["kind"])
            comment = _OTHER_KIND.match(source, end)
            if comment:
                end = comment.end()
                line_start, line_end = source.rfind("\n", 0, start) + 1, _line_end(source, end)
                if not source[line_start:start].strip() and not source[end:line_end].strip():
                    start, end = line_start, min(line_end + 1, len(source))
            edits.append((start, end, ""))
    elif "kind" in keywords:
        value = keywords["kind"].value
        start, end = at(value.lineno, value.col_offset), at(value.end_lineno, value.end_col_offset)
        edits.append((start, end, repr(kind)))
        line_end = _line_end(source, end)
        comment = _OTHER_KIND.search(source, end, line_end)
        if comment:  # "# or 'scatter'" names the other kind
            edits.append((comment.start(), comment.end(), other))
        elif call.func.attr != function and re.fullmatch(r",[ \t]*", source[end:line_end]):
            edits.append((line_end, line_end, other))  # graph_code's layout, from an older one without it
    else:  # from lmplot, or relplot's or catplot's own kind
        indent = _line_indent(source, at, call, keywords.get("height"))
        if indent:  # graph_code's layout: a line of its own, before "marker='o', height=4, ..."
            spot = at(keywords["height"].lineno, 0)
            edits.append((spot, spot, f"{indent}kind={kind!r},{other}\n"))
        else:
            paren = source.index("(", at(call.func.end_lineno, call.func.end_col_offset))
            edits.append((paren + 1, paren + 1, f"kind={kind!r}, "))

    had, key = ("markers" if call.func.attr == "lmplot" else "marker"), marker_keyword(kind)
    if had in keywords:
        keyword = keywords[had]
        if marker:
            value = keyword.value
            edits.append((at(value.lineno, value.col_offset), at(value.end_lineno, value.end_col_offset),
                          repr(marker)))
            if key != had:
                start = at(keyword.lineno, keyword.col_offset)
                edits.append((start, start + len(had), key))
        else:
            edits.append((*_keyword_span(source, at, keyword), ""))
    elif marker:
        if "height" in keywords:  # graph_code's layout: "marker='o', height=4, aspect=1.5,"
            height = keywords["height"]
            spot = at(height.lineno, height.col_offset)
            edits.append((spot, spot, f"{key}={marker!r}, "))
        elif "kind" in keywords and kind not in REGRESSION:
            kind_end = at(keywords["kind"].end_lineno, keywords["kind"].end_col_offset)
            comma = re.compile(r"[ \t]*,").match(source, kind_end)
            spot = comma.end() if comma else kind_end
            edits.append((spot, spot, f" {key}={marker!r}," if comma else f", {key}={marker!r}"))
        elif kind not in REGRESSION:  # kind was just added after the parenthesis; the marker goes with it
            index = next(i for i, edit in enumerate(edits) if edit[2].startswith("kind="))
            start, end, text = edits[index]
            edits[index] = (start, end, f"{text}{key}={marker!r}, ")
        else:
            paren = source.index("(", at(call.func.end_lineno, call.func.end_col_offset))
            edits.append((paren + 1, paren + 1, f"{key}={marker!r}, "))

    for start, end, text in sorted(edits, key=lambda edit: edit[0], reverse=True):
        source = source[:start] + text + source[end:]
    changed = read_graph(source)
    if changed is None or (changed.kind, changed.marker) != (kind, marker or None):
        raise ValueError("the chart's code couldn't be changed")
    return source


def frame_cell(notebook, graph_cell_id: str, frame: str | None) -> str | None:
    """The cell above a graph that makes its DataFrame (the nearest one
    assigning `frame`), if there is one."""
    if not frame:
        return None
    assigns = re.compile(rf"^{re.escape(frame)}\s*=(?!=)", re.M)
    above = notebook.cells[:notebook.index_of(graph_cell_id)]
    return next((cell.id for cell in reversed(above) if assigns.search(cell.source)), None)


def frame_data(source: str, frame: str) -> FrameData | None:
    """The data a DataFrame cell writes out, as dataframe_code does it
    (`df = pd.DataFrame({'Month': [...], ...})`), if it's written plainly."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    made = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == frame and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "DataFrame"
                and len(node.value.args) == 1):
            made = node  # the last one counts
    if made is None:
        return None
    table = _literal(made.value.args[0])
    if (not isinstance(table, dict) or not table or not all(isinstance(k, str) for k in table)
            or not all(isinstance(v, list) for v in table.values())
            or len({len(v) for v in table.values()}) != 1):
        return None
    return FrameData(list(table), [list(column) for column in table.values()])


# --- The notebook's DataFrames ---

@dataclass
class FrameCell:
    """A cell making a DataFrame as dataframe_code writes it: its id, the
    DataFrame's name, and its data."""

    cell_id: str
    name: str
    data: FrameData


def find_frames(notebook) -> list[FrameCell]:
    """The cells making a DataFrame as dataframe_code writes it (a chart's
    too), top to bottom: ones whose data can be updated, and that can be
    renamed."""
    found = []
    for cell in notebook.cells:
        try:
            tree = ast.parse(cell.source)
        except (SyntaxError, ValueError):
            continue
        names = [statement.targets[0].id for statement in tree.body
                 if isinstance(statement, ast.Assign) and len(statement.targets) == 1
                 and isinstance(statement.targets[0], ast.Name) and _makes_frame(statement, statement.targets[0].id)]
        data = frame_data(cell.source, names[-1]) if names else None
        if data is not None:
            found.append(FrameCell(cell.id, names[-1], data))
    return found


def frame_labels(frames) -> list[str]:
    """How the DataFrame dialog's list names each: "sales: Month, Sales,
    Cost (12 rows)", numbered if two would read the same."""
    labels = []
    for frame in frames:
        columns = frame.data.labels
        shown = ", ".join(columns[:4]) + (", …" if len(columns) > 4 else "")
        rows = len(frame.data.columns[0]) if frame.data.columns else 0
        labels.append(f"{frame.name}: {shown} ({rows} row{'' if rows == 1 else 's'})")
    return [f"{label} ({labels[:i].count(label) + 1})" if labels.count(label) > 1 else label
            for i, label in enumerate(labels)]


def update_frame_code(source: str, name: str, model, cells) -> str:
    """A DataFrame cell's code with `name = pd.DataFrame({...})` written
    afresh from the sheet's (row, col) cells, and its comment saying which
    cells it's of; anything else in it stays."""
    tree = ast.parse(source)
    statement = [statement for statement in tree.body if _makes_frame(statement, name)][-1]
    at = _Positions(source)
    start, end = at(statement.lineno, statement.col_offset), at(statement.end_lineno, statement.end_col_offset)
    comment, assignment = dataframe_parts(model, cells, name)
    comments = list(FRAME_COMMENT.finditer(source, 0, start))
    source = source[:start] + assignment + source[end:]
    if comments:
        source = source[:comments[-1].start()] + comment + source[comments[-1].end():]
    return source


# --- Renaming a graph's DataFrame ---

def used_names(notebook) -> set[str]:
    """Every name the notebook's code sets or uses: variables, functions,
    classes, imports, and parameters (and in cells that aren't plain Python,
    such as ones with a %magic, every word that could be one)."""
    names = set()
    for cell in notebook.cells:
        try:
            tree = ast.parse(cell.source)
        except (SyntaxError, ValueError):
            names.update(re.findall(r"[^\W\d]\w*", cell.source))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.alias):
                names.add(node.asname or node.name.split(".")[0])
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                names.update(node.names)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                names.add(node.name)
    return names


def rename_frame(notebook, frame_cell_id: str, old: str, new: str) -> tuple[dict[str, str], list[str]]:
    """The notebook's code with the DataFrame `old`, made in the cell
    `frame_cell_id` (as dataframe_code writes it), called `new` wherever it's
    used from there on: in that cell, and in the cells after it, until one
    sets `old` afresh to something else (another DataFrame of that name).
    A graph's "# df as a chart" comment, which names its DataFrame, changes
    too. Attributes and keywords of that name (x.df, f(df=1)) aren't it, nor
    is a function's parameter of that name. ({cell id: its code renamed} for
    the cells changed, [ids of cells mentioning `old` that couldn't be read as
    Python, so are left as they are])."""
    changed, unread = {}, []
    for cell in notebook.cells[notebook.index_of(frame_cell_id):]:
        try:
            tree = ast.parse(cell.source)
        except (SyntaxError, ValueError):
            if re.search(rf"(?<!\w){re.escape(old)}(?!\w)", cell.source):
                unread.append(cell.id)
            continue
        statements = tree.body
        if cell.id == frame_cell_id:  # from where it's made (the last, as frame_data reads it)
            made = [i for i, statement in enumerate(statements) if _makes_frame(statement, old)]
            if not made:
                raise ValueError(f"the cell doesn't make the DataFrame {old}")
            statements = statements[made[-1]:]
        uses, ended = [], False
        for index, statement in enumerate(statements):
            making = cell.id == frame_cell_id and index == 0  # (the statement making it sets it, of course)
            if not making and _rebinds(statement, old):
                ended = True
                break
            uses += _uses(statement, old)
        if uses:
            changed[cell.id] = _renamed(cell.source, uses, old, new)
        if ended:
            break
    return changed, unread


def _makes_frame(statement, name: str) -> bool:
    """Whether a statement is `name = pd.DataFrame(...)`."""
    return (isinstance(statement, ast.Assign) and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name) and statement.targets[0].id == name
            and isinstance(statement.value, ast.Call) and isinstance(statement.value.func, ast.Attribute)
            and statement.value.func.attr == "DataFrame")


def _rebinds(statement, name: str) -> bool:
    """Whether a statement sets `name` afresh, to something not made from
    it (df = df.dropna() is still the same DataFrame)."""
    if isinstance(statement, (ast.Assign, ast.AnnAssign)):
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        return (statement.value is not None and any(_binds(target, name) for target in targets)
                and not _uses(statement.value, name))
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return any((alias.asname or alias.name.split(".")[0]) == name for alias in statement.names)
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return statement.name == name
    if isinstance(statement, (ast.For, ast.AsyncFor)):
        return _binds(statement.target, name)
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return any(item.optional_vars is not None and _binds(item.optional_vars, name) for item in statement.items)
    return False


def _binds(target, name: str) -> bool:
    """Whether an assignment's target sets `name` (df, or a, df = ...; not df['x'] = ...)."""
    if isinstance(target, ast.Name):
        return target.id == name
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_binds(element, name) for element in target.elts)
    if isinstance(target, ast.Starred):
        return _binds(target.value, name)
    return False


def _uses(node, name: str) -> list:
    finder = _Uses(name)
    finder.visit(node)
    return finder.found


class _Uses(ast.NodeVisitor):
    """The Name nodes for a name, but not inside a function taking a
    parameter of that name (that's its own)."""

    def __init__(self, name: str):
        self.name = name
        self.found = []

    def visit_Name(self, node):
        if node.id == self.name:
            self.found.append(node)

    def _function(self, node):
        args = node.args
        params = [arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg) if arg]
        outside = [*args.defaults, *(default for default in args.kw_defaults if default is not None)]
        if not isinstance(node, ast.Lambda):  # (all of these are worked out where it's defined)
            outside += [*node.decorator_list, *([node.returns] if node.returns else []),
                        *(arg.annotation for arg in params if arg.annotation)]
        for part in outside:
            self.visit(part)
        if self.name not in {arg.arg for arg in params}:
            for part in node.body if isinstance(node.body, list) else [node.body]:
                self.visit(part)

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _function


def _renamed(source: str, uses, old: str, new: str) -> str:
    """The code with each of the Name nodes `uses` (of `old`) called `new`,
    and its "# old as a chart" comment, if it has one."""
    at = _Positions(source)
    edits = []
    for node in uses:
        start, end = at(node.lineno, node.col_offset), at(node.end_lineno, node.end_col_offset)
        if source[start:end] != old:
            raise ValueError(f"couldn't find {old} in the code to rename it")
        edits.append((start, end))
    comment = _FRAME_COMMENT.search(source)
    if comment and comment.group(1) == old:
        edits.append(comment.span(1))
    for start, end in sorted(set(edits), reverse=True):
        source = source[:start] + new + source[end:]
    return source


# --- Reading the code ---

def _plot_call(source: str):
    """(tree, the call) for the code's one relplot(...) or catplot(...) call, or None."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr in FUNCTION_KINDS]
    return (tree, calls[0]) if len(calls) == 1 else None


def _literal(node):
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _NOT_LITERAL


def _melted_columns(tree) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "melt":
            for keyword in node.keywords:
                if keyword.arg == "value_vars":
                    columns = _literal(keyword.value)
                    if isinstance(columns, list) and all(isinstance(c, str) for c in columns):
                        return columns
    return []


def _frame_name(source: str, tree) -> str | None:
    comment = _FRAME_COMMENT.search(source)
    if comment:
        return comment.group(1)
    names = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and re.fullmatch(r"df\d*", node.id)]
    return names[0] if names else None


class _Positions:
    """Turns ast's (line, UTF-8 byte column) positions into indexes in the source."""

    def __init__(self, source: str):
        self.lines = source.splitlines(keepends=True) or [""]
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))

    def __call__(self, lineno: int, col: int) -> int:
        line = self.lines[lineno - 1]
        return self.starts[lineno - 1] + len(line.encode("utf-8")[:col].decode("utf-8"))


def _line_indent(source: str, at, call, keyword) -> str:
    """The indentation of the line `keyword` is on, if its line starts with
    one of the call's keywords (else "")."""
    if keyword is None:
        return ""
    first = min((k for k in call.keywords if k.lineno == keyword.lineno), key=lambda k: k.col_offset)
    start = at(first.lineno, first.col_offset)
    indent = source[source.rfind("\n", 0, start) + 1:start]
    return indent if indent and not indent.strip() else ""


def _line_end(source: str, index: int) -> int:
    end = source.find("\n", index)
    return len(source) if end < 0 else end


def _keyword_span(source: str, at, keyword) -> tuple[int, int]:
    """Where `keyword=value` is, with its comma, or its whole line if it's
    alone on it."""
    start = at(keyword.lineno, keyword.col_offset)
    end = at(keyword.end_lineno, keyword.end_col_offset)
    comma = re.compile(r"[ \t]*,[ \t]*").match(source, end)
    if comma:
        end = comma.end()
    else:  # the last argument: take the comma before it instead
        before = re.search(r",[ \t]*\Z", source[:start])
        if before:
            start = before.start()
    line_start = source.rfind("\n", 0, start) + 1
    line_end = _line_end(source, end)
    if not source[line_start:start].strip() and not source[end:line_end].strip():
        return line_start, min(line_end + 1, len(source))
    return start, end
