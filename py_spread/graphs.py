"""The notebook's charts (graphs, in the code's names): finding cells that
draw a Seaborn chart (one sns.relplot or sns.catplot call), reading what
they draw, and changing it, for the Chart dialog.

Changing a graph's type or marker touches only kind=, marker=, and which of
relplot and catplot draws it, so anything else changed by hand in its cell
stays. Changing its columns writes the cell afresh, from the data in the
DataFrame's own cell.
"""

import ast
import re
from dataclasses import dataclass, field

from .notebook import CATEGORICAL, GRAPH_KINDS, FrameData, GraphColumns, GraphError

FUNCTION_KINDS = {"relplot": ("line", "scatter"), "catplot": ("strip", "swarm")}  # the kinds each draws here
DEFAULT_KINDS = {"relplot": "scatter", "catplot": "strip"}  # their kind when none is given
_FRAME_COMMENT = re.compile(r"^#\s*(\w+) as a (?:chart|graph)\b", re.M)  # as graph_code writes it (or did)
_OTHER_KIND = re.compile(r"[ \t]*#\s*or\s*(['\"])(line|scatter|strip|swarm)\1[^\n]*")  # "# or 'scatter'"
_OTHER_KINDS = {"line": "  # or 'scatter'", "scatter": "  # or 'line'", "strip": "  # or 'swarm'",
                "swarm": "  # or 'strip'"}  # as graph_code writes them
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
    relplot or catplot graph of a kind the Chart dialog has, with a plain
    marker."""
    found = _plot_call(source)
    if found is None:
        return None
    tree, call = found
    function = call.func.attr
    keywords = {k.arg: k.value for k in call.keywords if k.arg}
    kind = _literal(keywords["kind"]) if "kind" in keywords else DEFAULT_KINDS[function]
    marker = _literal(keywords["marker"]) if "marker" in keywords else None
    if kind not in FUNCTION_KINDS[function] or not (marker is None or isinstance(marker, str) and marker):
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
    return graph


def change_graph(source: str, kind: str, marker: str | None) -> str:
    """The cell's code with its graph's kind and marker changed (no marker:
    marker= is taken out), switching between relplot and catplot as the kind
    needs."""
    if kind not in GRAPH_KINDS:  # (for a hue or new columns, the cell is written afresh)
        raise ValueError(f"kind must be one of {', '.join(GRAPH_KINDS)}, not {kind!r}")
    if read_graph(source) is None:
        raise ValueError("the code doesn't draw a chart that can be changed")
    _tree, call = _plot_call(source)
    at = _Positions(source)
    keywords = {k.arg: k for k in call.keywords if k.arg}
    edits = []  # (start, end, new text), applied from the end backward

    function = "catplot" if kind in CATEGORICAL else "relplot"
    if call.func.attr != function:
        end = at(call.func.end_lineno, call.func.end_col_offset)
        edits.append((end - len(call.func.attr), end, function))

    other = _OTHER_KINDS[kind]
    if "kind" in keywords:
        value = keywords["kind"].value
        start, end = at(value.lineno, value.col_offset), at(value.end_lineno, value.end_col_offset)
        edits.append((start, end, repr(kind)))
        line_end = _line_end(source, end)
        comment = _OTHER_KIND.search(source, end, line_end)
        if comment:  # "# or 'scatter'" names the other kind
            edits.append((comment.start(), comment.end(), other))
        elif call.func.attr != function and re.fullmatch(r",[ \t]*", source[end:line_end]):
            edits.append((line_end, line_end, other))  # graph_code's layout, from an older one without it
    else:
        paren = source.index("(", at(call.func.end_lineno, call.func.end_col_offset))
        edits.append((paren + 1, paren + 1, f"kind={kind!r}, "))

    if "marker" in keywords:
        keyword = keywords["marker"]
        if marker:
            value = keyword.value
            edits.append((at(value.lineno, value.col_offset), at(value.end_lineno, value.end_col_offset),
                          repr(marker)))
        else:
            edits.append((*_keyword_span(source, at, keyword), ""))
    elif marker:
        if "height" in keywords:  # graph_code's layout: "marker='o', height=4, aspect=1.5,"
            height = keywords["height"]
            spot = at(height.lineno, height.col_offset)
            edits.append((spot, spot, f"marker={marker!r}, "))
        elif "kind" in keywords:
            kind_end = at(keywords["kind"].end_lineno, keywords["kind"].end_col_offset)
            comma = re.compile(r"[ \t]*,").match(source, kind_end)
            spot = comma.end() if comma else kind_end
            edits.append((spot, spot, f" marker={marker!r}," if comma else f", marker={marker!r}"))
        else:  # kind was just added after the parenthesis; the marker goes with it
            index = next(i for i, edit in enumerate(edits) if edit[2].startswith("kind="))
            start, end, text = edits[index]
            edits[index] = (start, end, f"{text}marker={marker!r}, ")

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
