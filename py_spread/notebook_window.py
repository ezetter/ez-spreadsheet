"""The notebook window: a Jupyter-style list of Python code cells and their
outputs, run in the sheet's kernel."""

import base64
import html
import keyword
import os
import re

from PySide6.QtCore import QEvent, QRegularExpression, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontDatabase,
    QImage,
    QKeySequence,
    QPalette,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .appearance import error_color, is_dark, next_zoom, scaled_font
from .notebook import joined_text as _text

MAX_OUTPUT_HEIGHT = 600  # taller outputs scroll within the cell
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")  # terminal colors in Python tracebacks
_DATAFRAME_GRID = re.compile(r'<table border="\d+" class="dataframe')  # pandas asks for a grid; Jupyter drops it
STATUS_TEXT = {"starting": "Starting Python…", "idle": "Python: idle", "busy": "Python: running",
               "stopped": "Python: stopped"}


def _table_css(line_color: str) -> str:
    """Tables (pandas DataFrames especially) as Jupyter shows them: no grid,
    a line under the column names, and everything right-aligned."""
    return ("table { border-collapse: collapse; } th, td { padding: 3px 10px; text-align: right; } "
            f"thead th {{ border-bottom: 1px solid {line_color}; }}")


def _image_size(output: dict, image: QImage, percent: int) -> str:
    """Width and height attributes showing an image output at its size in
    points, zoomed. (A Retina plot has twice as many pixels as points, and
    gives its size in points in its metadata.)"""
    metadata = output.get("metadata")
    points = metadata.get("image/png") if isinstance(metadata, dict) else None
    points = points if isinstance(points, dict) else {}
    scale = 1.0
    for side, pixels in (("width", image.width()), ("height", image.height())):
        size = points.get(side)
        if isinstance(size, (int, float)) and not isinstance(size, bool) and size > 0 and pixels:
            scale = size / pixels
            break
    scale *= percent / 100
    return f' width="{round(image.width() * scale)}" height="{round(image.height() * scale)}"'


class PythonHighlighter(QSyntaxHighlighter):
    """Colors keywords, strings, numbers, and comments."""

    def __init__(self, document, dark: bool):
        super().__init__(document)
        colors = (("#c792ea", "#c3e88d", "#f78c6c", "#7f8c98", "#82aaff") if dark
                  else ("#7a2d9e", "#2e7d32", "#b5520a", "#6a737d", "#1f5fbf"))
        keyword_color, string_color, number_color, comment_color, builtin_color = colors

        def style(color, bold=False, italic=False):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(700)
            fmt.setFontItalic(italic)
            return fmt

        words = "|".join(keyword.kwlist)
        self.rules = [
            (QRegularExpression(rf"\b({words})\b"), style(keyword_color, bold=True)),
            (QRegularExpression(r"\b(print|len|range|sum|min|max|abs|round|list|dict|set|str|int|float|"
                                r"pd|np|plt|df\d*)\b"), style(builtin_color)),
            (QRegularExpression(r"\b[0-9]+(\.[0-9]*)?([eE][+-]?[0-9]+)?\b"), style(number_color)),
            (QRegularExpression(r"'([^'\\]|\\.)*'|\"([^\"\\]|\\.)*\""), style(string_color)),
            (QRegularExpression(r"#[^\n]*"), style(comment_color, italic=True)),
        ]

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:  # later rules win: strings over keywords, comments over all
            matches = pattern.globalMatch(text)
            while matches.hasNext():
                match = matches.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class CodeEditor(QPlainTextEdit):
    """A code cell's editor: monospaced, as tall as its code, with Python-style
    indenting. Shift+Return runs the cell and moves on; Cmd+Return runs it."""

    run_requested = Signal(bool)  # advance to the next cell afterwards?
    focused = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTabChangesFocus(False)
        self.textChanged.connect(self._fit)
        self.highlighter = PythonHighlighter(self.document(), is_dark(self.palette()))
        self._fit()

    def set_dark(self, dark: bool) -> None:
        self.highlighter.setDocument(None)
        self.highlighter = PythonHighlighter(self.document(), dark)

    def _fit(self) -> None:
        lines = max(1, self.document().blockCount())
        height = (lines * self.fontMetrics().lineSpacing() + 2 * self.frameWidth()
                  + int(2 * self.document().documentMargin()) + 4)
        if self.horizontalScrollBar().maximum() > 0:
            height += self.horizontalScrollBar().sizeHint().height()
        self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit)  # the horizontal scroll bar may have come or gone

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange:  # zoomed
            self._fit()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focused.emit()

    def keyPressEvent(self, event):
        key, modifiers = event.key(), event.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if modifiers & Qt.ShiftModifier:
                self.run_requested.emit(True)
                return
            if modifiers & Qt.ControlModifier:  # Cmd on macOS
                self.run_requested.emit(False)
                return
            self._newline_with_indent()
            return
        if key == Qt.Key_Tab and not modifiers:
            self.insertPlainText("    ")
            return
        super().keyPressEvent(event)

    def _newline_with_indent(self) -> None:
        line = self.textCursor().block().text()[: self.textCursor().positionInBlock()]
        indent = line[: len(line) - len(line.lstrip(" "))]
        if line.rstrip().endswith(":"):
            indent += "    "
        self.insertPlainText("\n" + indent)


class OutputView(QTextBrowser):
    """A code cell's outputs: printed text, results (tables and images), and errors."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.NoFrame)
        self.viewport().setAutoFillBackground(False)  # on the cell's background, like Jupyter's outputs
        self.document().documentLayout().documentSizeChanged.connect(self._fit)
        self.outputs: list = []
        self.zoom = 100  # percent
        self._base_font = QFont(self.font())

    def set_zoom(self, percent: int) -> None:
        self.zoom = percent
        self.setFont(scaled_font(self._base_font, percent))
        self.show_outputs(self.outputs)  # images too

    def show_outputs(self, outputs: list) -> None:
        self.outputs = list(outputs)
        self.setVisible(bool(outputs))
        self.document().setDefaultStyleSheet(_table_css(self.palette().color(QPalette.Mid).name()))
        self.setHtml("".join(self._html(number, output) for number, output in enumerate(outputs)))

    def _html(self, number: int, output: dict) -> str:
        mono = "font-family: Menlo, Monaco, monospace;"
        kind = output.get("output_type")
        if kind == "stream":
            color = f"color: {error_color(self.palette())};" if output.get("name") == "stderr" else ""
            return f'<pre style="{mono} {color} margin: 2px 0;">{html.escape(_text(output.get("text", "")))}</pre>'
        if kind == "error":
            trace = _ANSI.sub("", "\n".join(_text(line) for line in output.get("traceback", [])))
            trace = trace or f"{output.get('ename', 'Error')}: {output.get('evalue', '')}"
            return (f'<pre style="{mono} color: {error_color(self.palette())}; margin: 2px 0;">'
                    f"{html.escape(trace)}</pre>")
        data = output.get("data")
        if not isinstance(data, dict):
            return ""
        if "image/png" in data:
            try:
                image = QImage.fromData(base64.b64decode(_text(data["image/png"])))
            except ValueError:  # not base64
                image = QImage()
            if not image.isNull():
                url = QUrl(f"output:image{number}")  # replaces the image shown here before
                self.document().addResource(QTextDocument.ImageResource, url, image)
                return f'<p><img src="{url.toString()}"{_image_size(output, image, self.zoom)}></p>'
        if "text/html" in data:
            page = _DATAFRAME_GRID.sub('<table class="dataframe', _text(data["text/html"]))
            return f"<div>{page}</div>"
        if "text/plain" in data:
            return f'<pre style="{mono} margin: 2px 0;">{html.escape(_text(data["text/plain"]))}</pre>'
        return ""

    def _fit(self, *_args) -> None:
        height = int(self.document().size().height()) + 2 * self.frameWidth() + 4
        if self.horizontalScrollBar().maximum() > 0:
            height += self.horizontalScrollBar().sizeHint().height()
        self.setFixedHeight(min(height, MAX_OUTPUT_HEIGHT))


class CellWidget(QFrame):
    """One code cell: its prompt ([3]), editor, and outputs."""

    def __init__(self, cell, zoom: int = 100, parent=None):
        super().__init__(parent)
        self.cell_id = cell.id
        self.setFrameShape(QFrame.StyledPanel)
        self.prompt = QLabel()
        self.prompt.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.editor = CodeEditor()
        self.editor.setPlainText(cell.source)
        self.output_view = OutputView()
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(self.editor)
        right.addWidget(self.output_view)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.prompt, 0, Qt.AlignTop)
        layout.addLayout(right, 1)
        self.set_zoom(zoom)
        self.show_cell(cell)
        self.set_current(False)

    def set_zoom(self, percent: int) -> None:
        code_font = scaled_font(QFontDatabase.systemFont(QFontDatabase.FixedFont), percent)
        self.prompt.setFont(code_font)
        self.prompt.setFixedWidth(self.prompt.fontMetrics().horizontalAdvance("[000]:") + 6)
        self.editor.setFont(code_font)
        if percent != self.output_view.zoom:
            self.output_view.set_zoom(percent)

    def show_cell(self, cell, running: bool = False) -> None:
        count = cell.execution_count
        self.prompt.setText("[*]:" if running else f"[{count if count is not None else ' '}]:")
        self.output_view.show_outputs(cell.outputs)

    def set_current(self, current: bool) -> None:
        color = self.palette().color(QPalette.Highlight).name() if current else "transparent"
        self.setStyleSheet(f"CellWidget {{ border: 2px solid {color}; border-radius: 4px; }}")


class NotebookWindow(QWidget):
    """The sheet's notebook. Closing it only hides it: its cells, and the
    kernel's variables, stay until the sheet is closed."""

    zoom_changed = Signal(int)  # percent

    def __init__(self, notebook, kernel, parent=None, save=None):
        super().__init__(parent, Qt.Window)
        self.notebook = notebook
        self.kernel = kernel
        self.zoom = 100  # percent, apart from the sheet's (View > Zoom zooms whichever is in front)
        self._zoom_base_fonts = None  # the toolbar's and labels' fonts at 100%, saved on first zoom
        self.resize(820, 700)
        self.set_sheet_name("Untitled")
        self.widgets: dict[str, CellWidget] = {}
        self.current_id: str | None = None
        self.running: set[str] = set()  # cells queued or running

        self.toolbar = QToolBar()
        self.actions_by_name = {}
        for name, tip, slot, shortcut in (
            ("Run", "Run this cell and move to the next (Shift+Return)", lambda: self.run_current(True), None),
            ("Run All", "Run every cell, top to bottom", self.run_all, None),
            ("+ Cell", "Add a cell below this one", self.add_cell_below, None),
            ("Delete", "Delete this cell", self.delete_current, None),
            ("↑", "Move this cell up", lambda: self.move_current(-1), None),
            ("↓", "Move this cell down", lambda: self.move_current(1), None),
            ("Interrupt", "Stop the running cell (⌘.)", self.interrupt, QKeySequence("Ctrl+.")),
            ("Restart", "Restart Python, forgetting every variable", self.restart, None),
        ):
            action = QAction(name, self)
            action.setToolTip(tip)
            action.triggered.connect(lambda _checked=False, s=slot: s())
            if shortcut:
                action.setShortcut(shortcut)
            self.toolbar.addAction(action)
            self.addAction(action)
            self.actions_by_name[name] = action
        self._state_text = STATUS_TEXT["idle" if kernel.has_kernel else "stopped"]
        self.status = QLabel(self._state_text)
        self._zoom_message = QTimer(self, singleShot=True, interval=2000)  # "Zoom 125%", then the state again
        self._zoom_message.timeout.connect(lambda: self.status.setText(self._state_text))
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)
        self.toolbar.addWidget(self.status)
        if save is not None:
            QShortcut(QKeySequence.Save, self, activated=save)  # the notebook is saved with the sheet

        self.cell_area = QWidget()
        self.cell_layout = QVBoxLayout(self.cell_area)
        self.cell_layout.setSpacing(6)
        self.cell_layout.addStretch()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.cell_area)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        self.problem.setVisible(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.problem)
        layout.addWidget(self.scroll, 1)

        notebook.cell_added.connect(self._on_cell_added)
        notebook.cell_removed.connect(self._on_cell_removed)
        notebook.cell_moved.connect(self._on_cell_moved)
        notebook.cell_updated.connect(self._on_cell_updated)
        notebook.reset.connect(self._rebuild)
        kernel.state_changed.connect(self._on_kernel_state)
        kernel.output.connect(self._on_output)
        kernel.finished.connect(self._on_finished)
        kernel.cancelled.connect(self._on_cancelled)
        kernel.failed.connect(self._on_failed)
        self._rebuild()

    def set_sheet_name(self, name: str) -> None:
        self.setWindowTitle(f"Notebook — {name}")

    # --- Zoom ---

    def zoom_in(self) -> None:
        self.set_zoom(next_zoom(self.zoom, 1))

    def zoom_out(self) -> None:
        self.set_zoom(next_zoom(self.zoom, -1))

    def set_zoom(self, percent: int) -> None:
        """Scale the toolbar, code, and outputs (text, tables, and plots) to
        `percent` of their normal size."""
        if self._zoom_base_fonts is None:
            self._zoom_base_fonts = {widget: QFont(widget.font()) for widget in self._zoomable_widgets()}
        self.zoom = percent
        for widget, base in self._zoom_base_fonts.items():
            widget.setFont(scaled_font(base, percent))
        for widget in self.widgets.values():
            widget.set_zoom(percent)
        self.status.setText(f"Zoom {percent}%")
        self._zoom_message.start()
        self.zoom_changed.emit(percent)

    def _zoomable_widgets(self) -> list:
        buttons = [self.toolbar.widgetForAction(action) for action in self.toolbar.actions()
                   if isinstance(self.toolbar.widgetForAction(action), QToolButton)]
        return [*buttons, self.status, self.problem]

    # --- Cells ---

    def _rebuild(self) -> None:
        for widget in self.widgets.values():
            widget.deleteLater()
        self.widgets.clear()
        self.running.clear()
        self.current_id = None
        for position, cell in enumerate(self.notebook.cells):
            self._on_cell_added(cell.id, position)
        if self.notebook.cells:
            self.set_current(self.notebook.cells[0].id)

    def _on_cell_added(self, cell_id: str, position: int) -> None:
        widget = CellWidget(self.notebook.cell(cell_id), self.zoom)
        widget.editor.textChanged.connect(
            lambda w=widget: self.notebook.set_source(w.cell_id, w.editor.toPlainText()))
        widget.editor.focused.connect(lambda w=widget: self.set_current(w.cell_id))
        widget.editor.run_requested.connect(lambda advance, w=widget: self.run_cell(w.cell_id, advance))
        self.widgets[cell_id] = widget
        self.cell_layout.insertWidget(position, widget)

    def _on_cell_removed(self, cell_id: str) -> None:
        widget = self.widgets.pop(cell_id, None)
        if widget is not None:
            widget.deleteLater()
        self.running.discard(cell_id)
        if self.current_id == cell_id:
            self.current_id = None

    def _on_cell_moved(self, cell_id: str, position: int) -> None:
        widget = self.widgets[cell_id]
        self.cell_layout.removeWidget(widget)
        self.cell_layout.insertWidget(position, widget)
        widget.editor.setFocus()

    def _on_cell_updated(self, cell_id: str) -> None:
        widget = self.widgets.get(cell_id)
        if widget is not None:
            widget.show_cell(self.notebook.cell(cell_id), cell_id in self.running)

    def set_current(self, cell_id: str, focus: bool = False) -> None:
        if cell_id not in self.widgets:
            return
        if self.current_id in self.widgets:
            self.widgets[self.current_id].set_current(False)
        self.current_id = cell_id
        widget = self.widgets[cell_id]
        widget.set_current(True)
        if focus:
            widget.editor.setFocus()
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(widget, 0, 40))

    def add_cell_below(self, source: str = "") -> str:
        position = self.notebook.index_of(self.current_id) + 1 if self.current_id else len(self.notebook.cells)
        cell = self.notebook.add_cell(source, position)
        self.set_current(cell.id, focus=True)
        return cell.id

    def delete_current(self) -> None:
        if self.current_id is None:
            return
        position = self.notebook.index_of(self.current_id)
        self.notebook.remove_cell(self.current_id)
        if self.notebook.cells:
            self.set_current(self.notebook.cells[min(position, len(self.notebook.cells) - 1)].id, focus=True)

    def move_current(self, offset: int) -> None:
        if self.current_id is not None:
            self.notebook.move_cell(self.current_id, offset)

    # --- Running ---

    def run_cell(self, cell_id: str, advance: bool = False) -> None:
        """Run a cell; with `advance`, then move to the next cell, adding one at the end."""
        cell = self.notebook.cell(cell_id)
        self.running.add(cell_id)
        self.notebook.clear_outputs(cell_id)
        self.kernel.run(cell_id, cell.source)
        if advance:
            position = self.notebook.index_of(cell_id)
            if position + 1 < len(self.notebook.cells):
                self.set_current(self.notebook.cells[position + 1].id, focus=True)
            else:
                self.set_current(cell_id)
                self.add_cell_below()

    def run_current(self, advance: bool = False) -> None:
        if self.current_id is not None:
            self.run_cell(self.current_id, advance)

    def run_all(self) -> None:
        for cell in list(self.notebook.cells):
            self.run_cell(cell.id)

    def interrupt(self) -> None:
        self.kernel.interrupt()

    def restart(self) -> None:
        self.kernel.restart()

    def _on_output(self, cell_id: str, output: dict) -> None:
        if cell_id in self.widgets:
            self.notebook.add_output(cell_id, output)

    def _on_finished(self, cell_id: str, count, _status: str) -> None:
        self.running.discard(cell_id)
        if cell_id in self.widgets:
            self.notebook.set_execution_count(cell_id, count)

    def _on_cancelled(self, cell_id: str) -> None:
        self.running.discard(cell_id)
        self._on_cell_updated(cell_id)

    def _on_kernel_state(self, state: str) -> None:
        self._state_text = STATUS_TEXT.get(state, state)
        self._zoom_message.stop()
        self.status.setText(self._state_text)
        if state in ("starting", "idle"):
            self.problem.setVisible(False)

    def _on_failed(self, message: str) -> None:
        self.problem.setText(message)
        self.problem.setStyleSheet(f"color: {error_color(self.palette())};")
        self.problem.setVisible(True)

    # --- Window ---

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.PaletteChange:  # switched between light and dark
            dark = is_dark(self.palette())
            for widget in self.widgets.values():
                widget.editor.set_dark(dark)
                widget.show_cell(self.notebook.cell(widget.cell_id), widget.cell_id in self.running)
                widget.set_current(widget.cell_id == self.current_id)


def kernel_folder(file_path: str | None) -> str:
    """Where the kernel starts: the sheet's folder, or Documents for a new sheet."""
    if file_path:
        return os.path.dirname(os.path.abspath(file_path))
    from PySide6.QtCore import QStandardPaths
    return QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
