"""Asking Claude about selected cells.

The selection's displayed values go to Claude as CSV, both in the message and
uploaded to Claude's code execution container, so Claude can compute with
Python (pandas, numpy, matplotlib, ...) and make charts. Files Claude saves
for the user, such as chart images, are downloaded with the Files API.

A ClaudeSession is one conversation: follow-up questions see the earlier
ones, and reuse the same container. It talks to the network, so the window
runs it on a worker thread; it reports progress through a listener.
"""

import csv
import io
import os
import threading

import anthropic

MODEL = "claude-opus-5-5"
EFFORT = "high"  # analysis is accuracy-sensitive work
MAX_TOKENS = 64000  # streaming, so long answers don't hit HTTP timeouts
# If Claude's safety classifiers decline a request, the API retries it on the
# model Anthropic recommends for that kind of refusal.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
CODE_EXECUTION = {"type": "code_execution_20260521", "name": "code_execution"}
MAX_CONTINUATIONS = 5  # a long code-running turn can pause; resume it this many times
INLINE_LIMIT = 50_000  # characters of CSV to include in the message itself
UPLOAD_NAME = "selection.csv"
UPLOAD_EXPIRY = 3600  # seconds; the upload is also deleted when the window closes
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".webp")

SYSTEM_PROMPT = f"""\
You're a data analyst helping someone who is using Py-Spread, a desktop \
spreadsheet. They've selected some cells and asked you about them.

The selected cells' displayed values are in their message as CSV, and the \
same CSV is uploaded to your code execution container as {UPLOAD_NAME}. Use \
code execution (Python with pandas, numpy, scipy, matplotlib, and so on) \
whenever computing would make your answer more accurate than reading the \
numbers, and to make a chart when one would help them understand the data.

To show them a chart or other file, save it and copy it into $OUTPUT_DIR in \
the same command, for example: \
`python chart.py && cp chart.png "$OUTPUT_DIR/" && ls "$OUTPUT_DIR"`. Only \
files copied into $OUTPUT_DIR reach them. Save charts as PNG, sized to read \
well at about 800 pixels wide, with a title and labeled axes.

They see your text and the files you share, not your code or its output, so \
state in your text the results you computed. Write in Markdown. Lead with the \
answer and keep it concise. Refer to cells by their names (such as B4) where \
that helps them find things in the sheet."""

CREDENTIALS_HELP = (
    "Py-Spread couldn't find Claude API credentials.\n\n"
    "Set your API key in the terminal before starting Py-Spread, for example by adding "
    "`export ANTHROPIC_API_KEY=...` to `~/.zshrc`, then open a new terminal and run "
    "`.venv/bin/python -m py_spread`. Or install Anthropic's `ant` command-line tool and "
    "run `ant auth login`. You can create an API key at platform.claude.com."
)


def selection_csv(model, cells) -> tuple[str, str]:
    """The displayed values of the selected (row, col) cells as CSV, covering
    the block from their top-left to bottom-right corner, and a sentence
    saying where that block is in the sheet."""
    from .references import cell_name, column_name

    rows = [row for row, _ in cells]
    cols = [col for _, col in cells]
    top, left, bottom, right = min(rows), min(cols), max(rows), max(cols)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in range(top, bottom + 1):
        writer.writerow([model.display_text(row, col) if (row, col) in cells else ""
                         for col in range(left, right + 1)])
    height, width = bottom - top + 1, right - left + 1
    description = (
        f"The selection is {cell_name(top, left)}:{cell_name(bottom, right)}, {height} row"
        f"{'s' if height != 1 else ''} by {width} column{'s' if width != 1 else ''}. "
        f"The CSV's first row is sheet row {top + 1}, and its columns are sheet columns "
        f"{column_name(left)} to {column_name(right)}."
    )
    return buffer.getvalue(), description


class Listener:
    """What a session reports while answering. The window's version turns
    these into Qt signals; every method is called on the worker thread."""

    def text(self, text: str) -> None: ...
    def status(self, text: str) -> None: ...
    def file(self, name: str, data: bytes) -> None: ...
    def finished(self, note: str) -> None: ...  # note is shown after the answer, if not empty
    def failed(self, message: str) -> None: ...


class ClaudeSession:
    def __init__(self, client, csv_text: str, description: str):
        self.client = client
        self.csv_text = csv_text
        self.description = description
        self.messages = []  # the conversation, appended to and never edited
        self.container_id = None
        self.upload_id = None
        self.cancel_requested = threading.Event()

    def ask(self, question: str, listener: Listener) -> None:
        """Send a question and stream the answer to the listener. Exactly one
        of listener.finished or listener.failed is called at the end."""
        self.cancel_requested.clear()
        asked_at = len(self.messages)
        try:
            self.messages.append({"role": "user", "content": self._question_content(question, listener)})
            self._answer(listener)
        except _Cancelled:
            self._forget_unanswered(asked_at)
            listener.finished("Stopped.")
        except _Refused as e:
            self._forget_unanswered(asked_at)
            listener.failed(str(e))
        except Exception as e:  # noqa: BLE001 -- every failure is reported to the user
            self._forget_unanswered(asked_at)
            listener.failed(describe_error(e))

    def cancel(self) -> None:
        self.cancel_requested.set()

    def close(self) -> None:
        """Delete the uploaded data. Errors are ignored: it expires anyway."""
        if self.upload_id:
            try:
                self.client.files.delete(self.upload_id)
            except Exception:  # noqa: BLE001
                pass
            self.upload_id = None

    def _question_content(self, question: str, listener: Listener):
        if self.messages:
            return question  # a follow-up: the data is already in the conversation
        if self.upload_id is None:  # (it's kept if a first question failed)
            listener.status("Sending the data…")
            uploaded = self.client.files.upload(
                file=(UPLOAD_NAME, self.csv_text.encode("utf-8"), "text/csv"),
                expires_in_seconds=UPLOAD_EXPIRY,
            )
            self.upload_id = uploaded.id
        if len(self.csv_text) <= INLINE_LIMIT:
            data = f"<data>\n{self.csv_text}</data>"
        else:
            data = (f"The data is too large to include here ({len(self.csv_text):,} characters); "
                    f"read it from {UPLOAD_NAME} with code execution.")
        text = f"{self.description}\n\n{data}\n\n{question}"
        return [{"type": "text", "text": text}, {"type": "container_upload", "file_id": self.upload_id}]

    def _answer(self, listener: Listener) -> None:
        for _ in range(MAX_CONTINUATIONS + 1):
            listener.status("Thinking…")
            message = self._stream_turn(listener)
            if message.stop_reason == "refusal":
                # A refusal can arrive mid-answer; the partial answer is discarded.
                category = getattr(message.stop_details, "category", None) if message.stop_details else None
                reason = f" ({category})" if category else ""
                raise _Refused(f"Claude declined to answer this{reason}. Try rephrasing the question.")
            # Append the whole response unchanged, so later turns keep Claude's
            # thinking and code-execution state.
            self.messages.append({"role": "assistant", "content": message.content})
            if message.container is not None:
                self.container_id = message.container.id
            self._download_files(message, listener)
            if message.stop_reason != "pause_turn":
                note = ("The answer was cut off because it reached the length limit."
                        if message.stop_reason == "max_tokens" else "")
                listener.finished(note)
                return
            listener.text("\n\n")  # a paused turn resumes in a new text block
        listener.finished("Claude was still working when Py-Spread stopped waiting. "
                          "Ask it to continue if you want more.")

    def _stream_turn(self, listener: Listener):
        params = dict(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=self.messages,
            tools=[CODE_EXECUTION],
            output_config={"effort": EFFORT},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        if self.container_id:
            params["container"] = self.container_id
        with self.client.beta.messages.stream(**params) as stream:
            for event in stream:
                if self.cancel_requested.is_set():
                    raise _Cancelled
                if event.type == "text":
                    listener.text(event.text)
                elif event.type == "content_block_start" and event.content_block.type == "server_tool_use":
                    listener.status("Running code…")
            return stream.get_final_message()

    def _download_files(self, message, listener: Listener) -> None:
        for file_id in generated_file_ids(message):
            if self.cancel_requested.is_set():
                raise _Cancelled
            metadata = self.client.files.retrieve_metadata(file_id)
            name = os.path.basename(metadata.filename) or "file"
            listener.status(f"Downloading {name}…")
            data = self.client.files.download(file_id).read()
            listener.file(name, data)
            try:
                self.client.files.delete(file_id)  # we have the bytes; don't leave a copy behind
            except Exception:  # noqa: BLE001
                pass

    def _forget_unanswered(self, asked_at: int) -> None:
        """Drop a question that got no answer, so the next one starts cleanly.
        (A question with part of an answer, from a paused turn, is kept.)"""
        if len(self.messages) == asked_at + 1:
            self.messages.pop()


class _Cancelled(Exception):
    pass


class _Refused(Exception):
    pass


def generated_file_ids(message) -> list[str]:
    """IDs of the files Claude shared from code execution in a response."""
    ids = []
    for block in message.content:
        if block.type == "bash_code_execution_tool_result" and block.content.type == "bash_code_execution_result":
            ids.extend(item.file_id for item in block.content.content)
    return ids


def describe_error(error: Exception) -> str:
    """A message for the user about a failed request."""
    if isinstance(error, TypeError) and "authentication" in str(error):
        return CREDENTIALS_HELP  # the SDK found no API key or login
    if isinstance(error, anthropic.AuthenticationError):
        return "The Claude API key was rejected. Check that it's correct and active.\n\n" + CREDENTIALS_HELP
    if isinstance(error, anthropic.PermissionDeniedError):
        return "This API key isn't allowed to do this: " + error.message
    if isinstance(error, anthropic.RateLimitError):
        return "Claude's rate limit was reached. Wait a minute and try again."
    if isinstance(error, anthropic.APIStatusError):
        if error.status_code >= 500:
            return f"Claude's service had a problem ({error.status_code}). Try again shortly."
        return f"The request failed ({error.status_code}): {error.message}"
    if isinstance(error, anthropic.APIConnectionError):
        return "Couldn't reach Claude. Check your internet connection."
    return f"Something went wrong: {error}"
