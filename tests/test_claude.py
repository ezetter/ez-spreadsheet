"""The Ask Claude feature, against a fake Anthropic client (no network)."""

import time
from types import SimpleNamespace as Obj

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QUrl
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from py_spread import claude
from py_spread.claude import CREDENTIALS_HELP, ClaudeSession, describe_error, selection_csv
from py_spread.model import SheetModel


# --- A fake client ---

def text_event(text):
    return Obj(type="text", text=text)


def code_started():
    return Obj(type="content_block_start", content_block=Obj(type="server_tool_use"))


def message(text="", stop_reason="end_turn", files=(), container="container_1", category=None):
    content = []
    if files:
        content.append(Obj(type="bash_code_execution_tool_result",
                           content=Obj(type="bash_code_execution_result",
                                       content=[Obj(file_id=f) for f in files])))
    if text:
        content.append(Obj(type="text", text=text))
    return Obj(content=content, stop_reason=stop_reason,
               container=Obj(id=container) if container else None,
               stop_details=Obj(category=category) if category else None)


class FakeStream:
    def __init__(self, events, final, on_iterate=None):
        self.events, self.final, self.on_iterate = events, final, on_iterate
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def __iter__(self):
        for event in self.events:
            if self.on_iterate:
                self.on_iterate()
            yield event

    def get_final_message(self):
        return self.final


class FakeClient:
    """Plays back scripted turns, recording each request."""

    def __init__(self, turns, files=None):
        self.turns = list(turns)
        self.requests = []
        self.uploads = []
        self.deleted = []
        self.stored = files or {}  # file_id -> (filename, bytes)
        self.files = Obj(upload=self._upload, retrieve_metadata=self._metadata,
                         download=self._download, delete=self.deleted.append)
        self.beta = Obj(messages=Obj(stream=self._stream))

    def _upload(self, file, expires_in_seconds):
        self.uploads.append((file, expires_in_seconds))
        return Obj(id="file_upload")

    def _metadata(self, file_id):
        return Obj(filename=self.stored[file_id][0])

    def _download(self, file_id):
        return Obj(read=lambda: self.stored[file_id][1])

    def _stream(self, **params):
        # Copy the history: the session keeps appending to the same list.
        self.requests.append({**params, "messages": list(params["messages"])})
        return self.turns.pop(0)


class Recorder:
    def __init__(self):
        self.texts, self.statuses, self.files, self.finished_notes, self.failures = [], [], [], [], []

    def text(self, t): self.texts.append(t)
    def status(self, t): self.statuses.append(t)
    def file(self, n, d): self.files.append((n, d))
    def finished(self, note): self.finished_notes.append(note)
    def failed(self, m): self.failures.append(m)


@pytest.fixture
def model(app):
    model = SheetModel(rows=20, cols=6)
    model.set_cells({(1, 1): "Month", (1, 2): "Sales", (2, 1): "Jan", (2, 2): "$1,200",
                     (3, 1): "Feb", (3, 2): "=C3*2"})
    return model


def block(top, left, bottom, right):
    return {(r, c) for r in range(top, bottom + 1) for c in range(left, right + 1)}


# --- Data ---

def test_selection_csv(model):
    text, description = selection_csv(model, block(1, 1, 3, 2))
    assert text == "Month,Sales\nJan,\"$1,200\"\nFeb,\"$2,400\"\n"  # displayed values
    assert description.startswith("The selection is B2:C4, 3 rows by 2 columns.")
    assert "sheet row 2" in description and "columns B to C" in description


def test_selection_csv_scattered(model):
    text, _ = selection_csv(model, {(1, 1), (2, 2)})
    assert text == "Month,\n,\"$1,200\"\n"


# --- The session ---

def test_first_question(model):
    client = FakeClient([FakeStream([text_event("Sales "), code_started(), text_event("rose.")],
                                    message("Sales rose."))])
    session = ClaudeSession(client, *selection_csv(model, block(1, 1, 3, 2)))
    listener = Recorder()
    session.ask("What's the trend?", listener)

    assert listener.texts == ["Sales ", "rose."]
    assert "Running code…" in listener.statuses
    assert listener.finished_notes == [""] and listener.failures == []
    (name, data, mime), expiry = client.uploads[0][0], client.uploads[0][1]
    assert (name, mime, expiry) == ("selection.csv", "text/csv", 3600)
    assert data.decode().startswith("Month,Sales")

    request = client.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["fallbacks"] == "default"
    assert request["tools"] == [{"type": "code_execution_20260521", "name": "code_execution"}]
    assert request["output_config"] == {"effort": "high"}
    assert "container" not in request
    content = request["messages"][0]["content"]
    assert content[1] == {"type": "container_upload", "file_id": "file_upload"}
    assert "<data>\nMonth,Sales" in content[0]["text"]
    assert content[0]["text"].endswith("What's the trend?")


def test_follow_up_reuses_container_and_history(model):
    client = FakeClient([FakeStream([text_event("A")], message("A")),
                         FakeStream([text_event("B")], message("B"))])
    session = ClaudeSession(client, *selection_csv(model, block(1, 1, 3, 2)))
    session.ask("first", Recorder())
    session.ask("second", Recorder())
    second = client.requests[1]
    assert second["container"] == "container_1"
    roles = [m["role"] for m in second["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert second["messages"][2]["content"] == "second"  # the data isn't sent again
    assert len(client.uploads) == 1


def test_paused_turn_is_resumed(model):
    client = FakeClient([FakeStream([text_event("Working")], message("Working", stop_reason="pause_turn")),
                         FakeStream([text_event("Done")], message("Done"))])
    session = ClaudeSession(client, *selection_csv(model, block(1, 1, 3, 2)))
    listener = Recorder()
    session.ask("q", listener)
    assert listener.texts == ["Working", "\n\n", "Done"]
    assert [m["role"] for m in client.requests[1]["messages"]] == ["user", "assistant"]
    assert listener.finished_notes == [""]


def test_generated_files_are_downloaded_and_removed(model):
    client = FakeClient([FakeStream([text_event("Here's a chart.")],
                                    message("Here's a chart.", files=["file_chart"]))],
                        files={"file_chart": ("../chart.png", b"PNGDATA")})
    session = ClaudeSession(client, *selection_csv(model, block(1, 1, 3, 2)))
    listener = Recorder()
    session.ask("Chart it", listener)
    assert listener.files == [("chart.png", b"PNGDATA")]  # only the base name is used
    assert client.deleted == ["file_chart"]


def test_refusal_discards_the_question(model):
    client = FakeClient([FakeStream([text_event("partial")], message("partial", stop_reason="refusal",
                                                                     category="cyber"))])
    session = ClaudeSession(client, *selection_csv(model, block(1, 1, 3, 2)))
    listener = Recorder()
    session.ask("q", listener)
    assert "declined" in listener.failures[0] and "cyber" in listener.failures[0]
    assert session.messages == []


def test_cut_off_answer_says_so(model):
    client = FakeClient([FakeStream([text_event("long")], message("long", stop_reason="max_tokens"))])
    session = ClaudeSession(client, *selection_csv(model, block(1, 1, 3, 2)))
    listener = Recorder()
    session.ask("q", listener)
    assert "cut off" in listener.finished_notes[0]


def test_cancel_stops_and_forgets_the_question(model):
    session = None
    client = FakeClient([FakeStream([text_event("a"), text_event("b")], message("ab"),
                                    on_iterate=lambda: session.cancel())])
    session = ClaudeSession(client, *selection_csv(model, block(1, 1, 3, 2)))
    listener = Recorder()
    session.ask("q", listener)
    assert listener.finished_notes == ["Stopped."]
    assert session.messages == []


def test_failure_keeps_the_upload_for_a_retry(model):
    def broken(**params):
        raise TypeError("Could not resolve authentication method. Expected one of api_key")

    client = FakeClient([])
    client.beta.messages.stream = broken
    session = ClaudeSession(client, *selection_csv(model, block(1, 1, 3, 2)))
    listener = Recorder()
    session.ask("q", listener)
    assert listener.failures == [CREDENTIALS_HELP]
    assert session.messages == []
    client.beta.messages.stream = client._stream
    client.turns = [FakeStream([text_event("ok")], message("ok"))]
    session.ask("q", Recorder())
    assert len(client.uploads) == 1  # reused


def test_large_selection_is_not_inlined(model, monkeypatch):
    monkeypatch.setattr(claude, "INLINE_LIMIT", 10)
    client = FakeClient([FakeStream([], message("x"))])
    session = ClaudeSession(client, *selection_csv(model, block(1, 1, 3, 2)))
    session.ask("q", Recorder())
    text = client.requests[0]["messages"][0]["content"][0]["text"]
    assert "<data>" not in text and "too large to include" in text


def test_close_deletes_upload(model):
    client = FakeClient([FakeStream([], message("x"))])
    session = ClaudeSession(client, *selection_csv(model, block(1, 1, 3, 2)))
    session.ask("q", Recorder())
    session.close()
    assert client.deleted == ["file_upload"]


def test_describe_error():
    assert describe_error(TypeError("Could not resolve authentication method")) == CREDENTIALS_HELP
    assert describe_error(ValueError("boom")) == "Something went wrong: boom"


# --- The window ---

def png_bytes(width=900, height=300) -> bytes:
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(0x3366CC)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


@pytest.fixture
def main_window(app):
    from py_spread.window import MainWindow
    window = MainWindow()
    window.model.set_cells({(0, 0): "x", (0, 1): "y", (1, 0): "1", (1, 1): "2"})
    window.show()
    yield window
    for w in list(window.claude_windows):
        w.close()
    window.setWindowModified(False)
    window.close()


def open_claude_window(main_window, client):
    from py_spread.claude_window import ClaudeWindow
    main_window.view.select_range(0, 0, 1, 1)
    window = ClaudeWindow(main_window.model, set(main_window._selected_cells()),
                          client_factory=lambda: client, parent=main_window)
    window.show()
    return window


def wait_for(predicate, timeout=5.0) -> bool:
    """Process Qt events until predicate() is true (the session runs on a thread)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def ask(window, question):
    window.prompt.setPlainText(question)
    window.ask_button.click()
    assert wait_for(lambda: not window.busy)


def test_menu_and_context_menu(main_window):
    claude_menu = [m for m in main_window.menuBar().actions() if m.text() == "Claude"][0].menu()
    assert claude_menu.actions() == [main_window.ask_claude_action]
    assert main_window.ask_claude_action in main_window.context_menu.actions()


def test_menu_opens_window_for_selection(main_window):
    main_window.view.select_range(0, 0, 1, 1)
    window = main_window.ask_claude()
    assert window.windowTitle() == "Ask Claude About A1:B2"
    assert window.csv_text == "x,y\n1,2\n"
    assert main_window.claude_windows == [window]


def test_window_shows_answer_and_chart(main_window):
    client = FakeClient([FakeStream([text_event("The **total** is 3.")],
                                    message("The total is 3.", files=["file_chart"]))],
                        files={"file_chart": ("chart.png", png_bytes())})
    window = open_claude_window(main_window, client)
    ask(window, "Sum it and chart it")
    text = window.transcript.toPlainText()
    assert "You: Sum it and chart it" in text
    assert "The total is 3." in text
    assert window.files == {"chart.png": png_bytes()}
    assert window.transcript.images["chart.png"].width() == 640  # scaled to fit
    assert "claude-file:chart.png" in window.markdown
    assert window.prompt.toPlainText() == ""
    assert window.ask_button.isEnabled() and not window.stop_button.isEnabled()


def test_window_saves_files(main_window, tmp_path, monkeypatch):
    client = FakeClient([FakeStream([], message("", files=["f"]))], files={"f": ("data.txt", b"hello")})
    window = open_claude_window(main_window, client)
    ask(window, "q")
    target = tmp_path / "out.txt"
    monkeypatch.setattr("py_spread.claude_window.QFileDialog.getSaveFileName",
                        lambda *args, **kwargs: (str(target), ""))
    window._on_link(QUrl("save:data.txt"))
    assert target.read_bytes() == b"hello"
    assert "[Save data.txt…](save:data.txt)" in window.markdown


def test_window_shows_problems(main_window):
    client = FakeClient([])

    def broken(**params):
        raise TypeError("Could not resolve authentication method.")

    client.beta.messages.stream = broken
    window = open_claude_window(main_window, client)
    ask(window, "q")
    assert "couldn't find Claude API credentials" in window.transcript.toPlainText()


def test_window_close_deletes_upload(main_window):
    client = FakeClient([FakeStream([], message("x"))])
    window = open_claude_window(main_window, client)
    ask(window, "q")
    window.close()
    assert wait_for(lambda: client.deleted == ["file_upload"])


def test_empty_question_is_ignored(main_window):
    client = FakeClient([])
    window = open_claude_window(main_window, client)
    window.ask_button.click()
    assert not window.busy and client.requests == []
