"""The Ask Claude window: a conversation with Claude about the selected cells,
in which Claude can also fill the sheet."""

import os
import threading
from urllib.parse import quote, unquote

import anthropic
from PySide6.QtCore import QObject, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .claude import IMAGE_TYPES, ClaudeSession, SheetAccess, selection_csv

IMAGE_WIDTH = 640  # images wider than this are scaled down to fit the transcript
FILE_SCHEME = "claude-file"  # transcript image URLs
SAVE_SCHEME = "save"  # transcript links that save a file Claude shared


class _Bridge(QObject):
    """Carries a session's progress from its worker thread to the window."""

    text_received = Signal(str)
    status_changed = Signal(str)
    file_received = Signal(str, object)
    done = Signal(str)
    error = Signal(str)
    sheet_task = Signal(object)  # a _SheetTask to run on the GUI thread

    # The session's Listener methods, called on the worker thread:
    def text(self, text):
        self.text_received.emit(text)

    def status(self, text):
        self.status_changed.emit(text)

    def file(self, name, data):
        self.file_received.emit(name, data)

    def finished(self, note):
        self.done.emit(note)

    def failed(self, message):
        self.error.emit(message)

    def run_on_sheet(self, task):
        """Run task() on the GUI thread, where the sheet lives, and wait for it."""
        job = _SheetTask(task)
        self.sheet_task.emit(job)
        job.done.wait()
        if isinstance(job.result, Exception):
            raise job.result
        return job.result


class _SheetTask:
    def __init__(self, task):
        self.task = task
        self.result = None
        self.done = threading.Event()

    def run(self):
        try:
            self.result = self.task()
        except Exception as e:  # noqa: BLE001 -- handed back to the worker thread
            self.result = e
        finally:
            self.done.set()


class Transcript(QTextBrowser):
    """Markdown transcript whose claude-file: images come from memory."""

    def __init__(self):
        super().__init__()
        self.images: dict[str, QImage] = {}
        self.setOpenLinks(False)  # links are handled by the window

    def loadResource(self, kind, url):
        if url.scheme() == FILE_SCHEME:
            return self.images.get(unquote(url.path()))
        return super().loadResource(kind, url)


class ClaudeWindow(QWidget):
    """Ask Claude about a snapshot of the selected cells, or ask it to fill the
    sheet. Charts and other files Claude shares appear in the transcript with
    Save links. `view`, if given, selects the cells Claude writes."""

    def __init__(self, model, cells, client_factory=anthropic.Anthropic, parent=None, view=None):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(760, 680)
        self.client_factory = client_factory
        self.csv_text, self.description = selection_csv(model, cells)
        rows = [row for row, _ in cells]
        cols = [col for _, col in cells]
        from .references import cell_name
        self.range_name = f"{cell_name(min(rows), min(cols))}:{cell_name(max(rows), max(cols))}"
        self.setWindowTitle(f"Ask Claude: {self.range_name}")
        self.model = model
        self.view = view

        self.session: ClaudeSession | None = None
        self.busy = False
        self.markdown = ""
        self.files: dict[str, bytes] = {}
        self.bridge = _Bridge()
        self.bridge.text_received.connect(self._on_text)
        self.bridge.status_changed.connect(self._on_status)
        self.bridge.file_received.connect(self._on_file)
        self.bridge.done.connect(self._on_done)
        self.bridge.error.connect(self._on_error)
        self.bridge.sheet_task.connect(lambda job: job.run())
        self._render_timer = QTimer(self, singleShot=True, interval=100)  # streaming text redraws at most 10×/s
        self._render_timer.timeout.connect(self._render)

        intro = QLabel(f"Claude sees the values shown in {self.range_name} "
                       f"({len(set(rows))} rows × {len(set(cols))} columns). It can run Python to "
                       "calculate and make charts, and fill cells when you ask it to "
                       "(each fill can be undone).")
        intro.setWordWrap(True)
        self.transcript = Transcript()
        self.transcript.anchorClicked.connect(self._on_link)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "Ask about the selected cells, such as “What trends do you see?”, or ask Claude "
            "to fill the sheet, such as “Fill a column with angles 0–360 by 10s and their "
            "sines.”  Press ⌘↩ to send.")
        self.prompt.setMaximumHeight(90)
        self.status = QLabel()
        self.ask_button = QPushButton("Ask")
        self.ask_button.setDefault(True)
        self.ask_button.clicked.connect(self.ask)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.ask)  # ⌘↩ on macOS

        buttons = QHBoxLayout()
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.ask_button)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.transcript, 1)
        layout.addWidget(self.prompt)
        layout.addLayout(buttons)
        self.prompt.setFocus()

    def ask(self) -> None:
        question = self.prompt.toPlainText().strip()
        if not question or self.busy:
            return
        if self.session is None:
            sheet = SheetAccess(self.model, on_write=self._show_written)
            self.session = ClaudeSession(self.client_factory(), self.csv_text, self.description, sheet)
        if self.markdown:
            self.markdown += "\n\n---\n\n"  # a rule between questions
        self.markdown += f"**You:** {question}\n\n**Claude:** "
        self.prompt.clear()
        self._set_busy(True)
        self._render()
        threading.Thread(target=self.session.ask, args=(question, self.bridge), daemon=True).start()

    def _show_written(self, top: int, left: int, bottom: int, right: int) -> None:
        if self.view is not None:
            self.view.select_range(top, left, bottom, right)

    def stop(self) -> None:
        if self.session is not None and self.busy:
            self.session.cancel()
            self.status.setText("Stopping…")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.ask_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        if not busy:
            self.status.setText("")

    def _on_text(self, text: str) -> None:
        self.markdown += text
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _on_status(self, text: str) -> None:
        self.status.setText(text)

    def _on_file(self, name: str, data: bytes) -> None:
        name = self._unique_name(name)
        self.files[name] = data
        link = quote(name)
        image = QImage.fromData(data) if name.lower().endswith(IMAGE_TYPES) else QImage()
        if not image.isNull():
            if image.width() > IMAGE_WIDTH:
                image = image.scaledToWidth(IMAGE_WIDTH, Qt.SmoothTransformation)
            self.transcript.images[name] = image
            self.markdown += f"\n\n![{name}]({FILE_SCHEME}:{link})\n\n"
        self.markdown += f"\n\n[Save {name}…]({SAVE_SCHEME}:{link})\n\n"
        self._render()

    def _on_done(self, note: str) -> None:
        if note:
            self.markdown += f"\n\n*{note}*"
        self._set_busy(False)
        self._render()

    def _on_error(self, message: str) -> None:
        self.markdown += f"\n\n**Problem:** {message}"
        self._set_busy(False)
        self._render()

    def _render(self) -> None:
        self._render_timer.stop()
        scrollbar = self.transcript.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        self.transcript.setMarkdown(self.markdown)
        if at_bottom:  # follow the answer as it arrives, unless scrolled up to read
            scrollbar.setValue(scrollbar.maximum())

    def _unique_name(self, name: str) -> str:
        stem, ext = os.path.splitext(name)
        candidate, n = name, 2
        while candidate in self.files:
            candidate, n = f"{stem}-{n}{ext}", n + 1
        return candidate

    def _on_link(self, url: QUrl) -> None:
        if url.scheme() == SAVE_SCHEME:
            self._save_file(unquote(url.path()))
        elif url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    def _save_file(self, name: str) -> None:
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getSaveFileName(self, "Save File", os.path.join(documents, name))
        if path:
            with open(path, "wb") as f:
                f.write(self.files[name])
            self.status.setText(f"Saved {os.path.basename(path)}.")

    def closeEvent(self, event):
        if self.session is not None:
            self.session.cancel()
            # Delete the uploaded data in the background; it expires anyway.
            threading.Thread(target=self.session.close, daemon=True).start()
        super().closeEvent(event)

