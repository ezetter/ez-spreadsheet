"""The notebook's graphs: finding cells that draw a Seaborn graph (one
sns.relplot call), reading their type and marker, and changing them in the
code, for the Graph dialog.

Only the kind= and marker= arguments are touched, so anything else changed
by hand in a graph's cell stays as it is.
"""

import ast
import re
from dataclasses import dataclass, field

KINDS = ("line", "scatter")
DEFAULT_KIND = "scatter"  # relplot's kind when none is given
_FRAME_COMMENT = re.compile(r"^#\s*(\w+) as a graph\b", re.M)  # as graph_code writes it
_OTHER_KIND = re.compile(r"#\s*or\s*(['\"])(line|scatter)\1")  # graph_code's "# or 'scatter'"
_NOT_LITERAL = object()


@dataclass
class GraphCell:
    cell_id: str
    kind: str  # "line" or "scatter"
    marker: str | None
    frame: str | None = None  # the DataFrame it graphs, if known
    x_label: str | None = None
    y_labels: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        """What it graphs: "Sales and Cost against Month"."""
        if not self.x_label or not self.y_labels:
            return f"a graph of {self.frame}" if self.frame else "a graph"
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
    to bottom."""
    graphs = []
    for cell in notebook.cells:
        graph = read_graph(cell.source)
        if graph is not None:
            graph.cell_id = cell.id
            graphs.append(graph)
    return graphs


def read_graph(source: str) -> GraphCell | None:
    """The graph a cell's code draws, or None if it doesn't draw exactly one
    relplot graph with a line or scatter kind and a plain marker."""
    found = _relplot(source)
    if found is None:
        return None
    tree, call = found
    keywords = {k.arg: k.value for k in call.keywords if k.arg}
    kind = _literal(keywords["kind"]) if "kind" in keywords else DEFAULT_KIND
    marker = _literal(keywords["marker"]) if "marker" in keywords else None
    if kind not in KINDS or not (marker is None or isinstance(marker, str) and marker):
        return None
    graph = GraphCell("", kind, marker, frame=_frame_name(source, tree))
    x, y = _literal(keywords.get("x")), _literal(keywords.get("y"))
    graph.x_label = x if isinstance(x, str) else None
    if "hue" in keywords:  # graph_code's long form: the y columns were melted into one
        graph.y_labels = _melted_columns(tree)
    elif isinstance(y, str):
        graph.y_labels = [y]
    return graph


def change_graph(source: str, kind: str, marker: str | None) -> str:
    """The cell's code with its graph's kind and marker changed (no marker:
    marker= is taken out)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be 'line' or 'scatter', not {kind!r}")
    if read_graph(source) is None:
        raise ValueError("the code doesn't draw a graph that can be changed")
    _tree, call = _relplot(source)
    at = _Positions(source)
    keywords = {k.arg: k for k in call.keywords if k.arg}
    edits = []  # (start, end, new text), applied from the end backward

    if "kind" in keywords:
        value = keywords["kind"].value
        start, end = at(value.lineno, value.col_offset), at(value.end_lineno, value.end_col_offset)
        edits.append((start, end, repr(kind)))
        line_end = _line_end(source, end)
        comment = _OTHER_KIND.search(source, end, line_end)
        if comment:  # "# or 'scatter'" now names the other kind
            other = KINDS[1 - KINDS.index(kind)]
            edits.append((comment.start(), comment.end(), f"# or {other!r}"))
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
            start, end, text = edits[0]
            edits[0] = (start, end, f"{text}marker={marker!r}, ")

    for start, end, text in sorted(edits, key=lambda edit: edit[0], reverse=True):
        source = source[:start] + text + source[end:]
    changed = read_graph(source)
    if changed is None or (changed.kind, changed.marker) != (kind, marker or None):
        raise ValueError("the graph's code couldn't be changed")
    return source


def frame_cell(notebook, graph_cell_id: str, frame: str | None) -> str | None:
    """The cell above a graph that makes its DataFrame (the nearest one
    assigning `frame`), if there is one."""
    if not frame:
        return None
    assigns = re.compile(rf"^{re.escape(frame)}\s*=(?!=)", re.M)
    above = notebook.cells[:notebook.index_of(graph_cell_id)]
    return next((cell.id for cell in reversed(above) if assigns.search(cell.source)), None)


# --- Reading the code ---

def _relplot(source: str):
    """(tree, the call) for the code's one relplot(...) call, or None."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "relplot"]
    return (tree, calls[0]) if len(calls) == 1 else None


def _literal(node):
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
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
