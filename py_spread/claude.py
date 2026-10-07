"""Asking Claude about the sheet, and having Claude fill it.

The selection's displayed values go to Claude as CSV, both in the message and
uploaded to Claude's code execution container, so Claude can compute with
Python (pandas, numpy, matplotlib, ...) and make charts. Files Claude saves
for the user, such as chart images, are downloaded with the Files API.

Claude can also look at and change the sheet through two tools that run here:
read_cells and write_cells. Writes take effect at once, each as one undoable
step, and can be formulas, so generated data stays live.

A ClaudeSession is one conversation: follow-up questions see the earlier
ones, and reuse the same container. It talks to the network, so the window
runs it on a worker thread; it reports progress through a listener, which
also runs the sheet tools on the GUI thread.
"""

import csv
import io
import json
import os
import threading

import anthropic

from .references import cell_name, column_name, parse_cell_name

MODEL = "claude-opus-5-5"
EFFORT = "high"  # analysis is accuracy-sensitive work
MAX_TOKENS = 64000  # streaming, so long answers don't hit HTTP timeouts
# If Claude's safety classifiers decline a request, the API retries it on the
# model Anthropic recommends for that kind of refusal.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
CODE_EXECUTION = {"type": "code_execution_20260521", "name": "code_execution"}
MAX_STEPS = 25  # requests per question: tool calls and paused turns each take one
MAX_PARSE_RETRIES = 2  # re-sends of a turn whose tool input arrived as unreadable JSON
INLINE_LIMIT = 50_000  # characters of CSV to include in the message itself
UPLOAD_NAME = "selection.csv"
UPLOAD_EXPIRY = 3600  # seconds; the upload is also deleted when the window closes
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
MAX_WRITE_CELLS = 100_000  # per write_cells call
MAX_READ_CELLS = 10_000  # per read_cells call
PREVIEW_ROWS = 5  # rows of a write shown back to Claude, to check its formulas

FORMULA_LANGUAGE = """\
Py-Spread's formulas start with = and use + - * / ^ and parentheses. ^ binds \
tighter than unary minus (-2^2 is -4) and is right-associative. References \
look like A1 or $A$1; ranges like A1:B9 can only be function arguments. The \
only functions are SUM, MEAN, MEDIAN, and STDDEV (sample standard deviation), \
which take ranges, cells, and numbers; SIN, COS, and TAN, which take an angle \
in the sheet's angle unit, degrees or radians (you're told which, and told \
again if they switch it); EXP(x), e to the power x; and POW(x, y), x to the \
power y. PI is the constant pi (=2*PI*A1). Cells can have names, such as r \
for B2; a formula can use a name in place of that cell's reference (=PI*r^2), \
and read_cells lists the sheet's names. Names are case-sensitive and can look \
like cell references: if a cell is named A1, a bare A1 in a formula means \
that name, and $A1, A$1, or $A$1 mean cell A1. Ranges (A1:B9) always mean \
cells. A column can have a name too: with column C named t, t1 means $C1, t2 \
means $C2, and so on, also as range corners (=SUM(t1:t9)); filling or \
copying a formula down turns t1 into t2. There are no other functions: no \
SQRT, LN, ABS, IF, or text functions (use x^0.5 for a square root). Text that \
doesn't start with = is stored as typed; numbers may include a dollar sign and \
thousands separators ($1,234.50), and keep that style."""

SYSTEM_PROMPT = f"""\
You're a data analyst helping someone who is using Py-Spread, a desktop \
spreadsheet. They've selected some cells and either asked about them or asked \
you to put something in the sheet.

The selected cells' displayed values are in their first message as CSV, and \
the same CSV is uploaded to your code execution container as {UPLOAD_NAME}. \
Use code execution (Python with pandas, numpy, scipy, matplotlib, and so on) \
whenever computing would make your answer more accurate than reading the \
numbers, and to make a chart when one would help them understand the data.

To show them a chart or other file, save it and copy it into $OUTPUT_DIR in \
the same command, for example: \
`python chart.py && cp chart.png "$OUTPUT_DIR/" && ls "$OUTPUT_DIR"`. Only \
files copied into $OUTPUT_DIR reach them. Save charts as PNG, sized to read \
well at about 800 pixels wide, with a title and labeled axes.

You can look at any part of the sheet with read_cells, and change it with \
write_cells. Write only when they ask you to put something in the sheet. \
Unless they say where, start at the top-left cell of their selection. Don't \
overwrite cells that hold data unless they ask you to; check with read_cells \
first if you aren't sure the cells are empty. Writes take effect immediately, \
and they can undo each one. When values follow from other cells, write \
formulas that refer to those cells, so the sheet stays live; write plain \
values for data that doesn't depend on other cells, or that needs \
calculations the formulas can't do. Add a header label above (or beside) \
each column (or row) you fill, unless they say otherwise.

{FORMULA_LANGUAGE}

They see your text and the files you share, not your code, its output, or \
your tool calls, so state in your text the results you computed and what you \
wrote where. Write in Markdown. Lead with the answer and keep it concise. \
Refer to cells by their names (such as B4) where that helps them find things \
in the sheet."""

READ_TOOL = {
    "name": "read_cells",
    "description": (
        "Read a block of the sheet. Returns each cell's displayed value as CSV, then lists "
        "the formulas in the block. Empty cells are empty fields. At most "
        f"{MAX_READ_CELLS:,} cells per call."
    ),
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "range": {"type": "string", "description": "The cells to read, such as A1:D20 or B3."},
        },
        "required": ["range"],
        "additionalProperties": False,
    },
}

WRITE_TOOL = {
    "name": "write_cells",
    "description": (
        "Write a block of cells into the sheet, starting at `start` and filling rightward and "
        "downward: rows[0] goes in start's row, rows[1] in the row below, and so on. Each "
        "value is a string: a number, text, or a Py-Spread formula starting with =. An empty "
        "string empties that cell. The write takes effect immediately as one step the user can "
        "undo. Returns the range written, any cells showing errors, and the first rows as "
        f"displayed. At most {MAX_WRITE_CELLS:,} cells per call."
    ),
    "eager_input_streaming": True,  # big blocks of data stream in as Claude writes them
    "input_schema": {
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "Top-left cell of the block, such as A1."},
            "rows": {
                "type": "array",
                "description": "The rows of the block, top to bottom; each is a list of cell values, left to right.",
                "items": {"type": "array", "items": {"type": "string"}},
            },
        },
        "required": ["start", "rows"],
        "additionalProperties": False,
    },
}

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


class ToolInputError(Exception):
    """A tool call's input can't be used; the message goes back to Claude."""


class SheetAccess:
    """The sheet as Claude's tools see it. Its methods must run on the GUI
    thread; `on_write` is told the (top, left, bottom, right) block written."""

    def __init__(self, model, on_write=None):
        self.model = model
        self.on_write = on_write

    def angle_unit(self) -> str:
        return self.model.angle_unit

    def read(self, range_text: str) -> str:
        top, left, bottom, right = _parse_range(range_text)
        if (bottom - top + 1) * (right - left + 1) > MAX_READ_CELLS:
            raise ToolInputError(f"That's more than {MAX_READ_CELLS:,} cells; read a smaller block.")
        model = self.model
        if bottom >= model.rowCount() or right >= model.columnCount():
            raise ToolInputError(f"The sheet is {model.rowCount()} rows by {model.columnCount()} "
                                 f"columns (A1:{cell_name(model.rowCount() - 1, model.columnCount() - 1)}).")
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        formulas = []
        for row in range(top, bottom + 1):
            writer.writerow([model.display_text(row, col) for col in range(left, right + 1)])
            for col in range(left, right + 1):
                raw = model.get_cell(row, col)
                if raw.startswith("="):
                    formulas.append(f"{cell_name(row, col)}: {raw}")
        text = f"{cell_name(top, left)}:{cell_name(bottom, right)} as displayed:\n{buffer.getvalue()}"
        if formulas:
            text += "Formulas:\n" + "\n".join(formulas)
        else:
            text += "No formulas."
        cell_names = {name: cell for name, cell in model.cell_names().items() if cell}
        if cell_names:
            text += "\nNamed cells in the sheet: " + ", ".join(
                f"{name} = {cell_name(*cell)}" for name, cell in cell_names.items())
        if model.column_names():
            text += "\nNamed columns in the sheet: " + ", ".join(
                f"{name} = column {column_name(col)} ({name}1 is {column_name(col)}1)"
                for name, col in model.column_names().items())
        return text

    def write(self, start: str, rows: list[list[str]]) -> str:
        top, left = _parse_cell(start)
        width = max((len(row) for row in rows), default=0)
        if not rows or width == 0:
            raise ToolInputError("rows is empty; there's nothing to write.")
        if len(rows) * width > MAX_WRITE_CELLS:
            raise ToolInputError(f"That's more than {MAX_WRITE_CELLS:,} cells; write it in smaller blocks.")
        bottom, right = top + len(rows) - 1, left + width - 1
        model = self.model
        model.ensure_size(bottom + 1, right + 1)
        writes = {(top + r, left + c): value for r, row in enumerate(rows) for c, value in enumerate(row)}
        model.set_cells(writes, "Claude Fill")
        if self.on_write:
            self.on_write(top, left, bottom, right)

        errors = [cell_name(*key) + " " + model.display_text(*key) for key in sorted(writes)
                  if model.display_text(*key).startswith("#")]
        text = f"Wrote {len(rows)} rows by {width} columns to {cell_name(top, left)}:{cell_name(bottom, right)}."
        if errors:
            shown = ", ".join(errors[:20]) + (f", and {len(errors) - 20} more" if len(errors) > 20 else "")
            text += f" {len(errors)} cells show errors: {shown}."
        preview = io.StringIO()
        writer = csv.writer(preview, lineterminator="\n")
        for row in range(top, min(bottom, top + PREVIEW_ROWS - 1) + 1):
            writer.writerow([model.display_text(row, col) for col in range(left, right + 1)])
        return text + f"\nThe first rows as displayed:\n{preview.getvalue()}"


def _parse_cell(text) -> tuple[int, int]:
    try:
        row, col = parse_cell_name(str(text).strip())
    except ValueError:
        row = -1
    if row < 0:
        raise ToolInputError(f"{text!r} isn't a cell name such as A1.")
    return row, col


def _parse_range(text) -> tuple[int, int, int, int]:
    first, _, last = str(text).partition(":")
    r1, c1 = _parse_cell(first)
    r2, c2 = _parse_cell(last) if last else (r1, c1)
    return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


def _cell_text(value) -> str:
    """A write_cells value as cell text. The schema asks for strings, but a
    stray number or null is accepted rather than failing the whole write."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return value
    raise ToolInputError(f"Cell values must be strings; got {json.dumps(value)[:80]}.")


class Listener:
    """What a session reports while answering, and how it reaches the sheet.
    The window's version turns these into Qt signals; every method is called
    on the worker thread."""

    def text(self, text: str) -> None: ...
    def status(self, text: str) -> None: ...
    def file(self, name: str, data: bytes) -> None: ...
    def finished(self, note: str) -> None: ...  # note is shown after the answer, if not empty
    def failed(self, message: str) -> None: ...

    def run_on_sheet(self, task):
        """Run task() where the sheet can be used (the GUI thread), and return its result."""
        return task()


class ClaudeSession:
    def __init__(self, client, csv_text: str, description: str, sheet: SheetAccess | None = None):
        self.client = client
        self.csv_text = csv_text
        self.description = description
        self.sheet = sheet  # None: Claude can't read or write the sheet
        self.told_angle_unit = None  # the angle unit Claude was last told
        self.messages = []  # the conversation, appended to and never edited
        self.container_id = None
        self.upload_id = None
        self.cancel_requested = threading.Event()

    def ask(self, question: str, listener: Listener) -> None:
        """Send a question and stream the answer to the listener, running any
        sheet tools Claude calls. Exactly one of listener.finished or
        listener.failed is called at the end."""
        self.cancel_requested.clear()
        asked_at = len(self.messages)
        try:
            self.messages.append({"role": "user", "content": self._question_content(question, listener)})
            self._answer(listener)
        except _Cancelled:
            self._settle(asked_at, "The user stopped this before it ran.")
            listener.finished("Stopped.")
        except _Refused as e:
            self._settle(asked_at, "Not run: the response was declined.")
            listener.failed(str(e))
        except Exception as e:  # noqa: BLE001 -- every failure is reported to the user
            self._settle(asked_at, "Not run: the request failed.")
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

    @property
    def tools(self) -> list[dict]:
        return [CODE_EXECUTION] + ([READ_TOOL, WRITE_TOOL] if self.sheet else [])

    def _question_content(self, question: str, listener: Listener):
        # Tell Claude the angle unit at the start, and again if it's switched,
        # so the trig formulas it writes take the right unit.
        unit = listener.run_on_sheet(self.sheet.angle_unit) if self.sheet else None
        if unit != self.told_angle_unit:
            question = f"The sheet takes angles in {unit}.\n\n{question}"
        content = self._content(question, listener)
        self.told_angle_unit = unit
        return content

    def _content(self, question: str, listener: Listener):
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
        parse_retries = 0
        for _ in range(MAX_STEPS):
            listener.status("Thinking…")
            try:
                message = self._stream_turn(listener)
            except ValueError:
                # A tool input the SDK couldn't parse at all. The turn never
                # completed, so there's nothing to answer: send it again.
                parse_retries += 1
                if parse_retries > MAX_PARSE_RETRIES:
                    raise
                continue
            parse_retries = 0
            if message.stop_reason == "refusal":
                # A refusal can arrive mid-answer; the partial answer is discarded.
                category = getattr(message.stop_details, "category", None) if message.stop_details else None
                reason = f" ({category})" if category else ""
                raise _Refused(f"Claude declined to answer this{reason}. Try rephrasing the question.")
            tool_uses = [block for block in message.content if block.type == "tool_use"]
            if message.stop_reason == "max_tokens" and tool_uses:
                # The tool call was cut off mid-input, so it can't be run or
                # answered; leave the turn out of the conversation.
                listener.finished("The answer was cut off because it reached the length limit.")
                return
            # Append the whole response unchanged, so later turns keep Claude's
            # thinking and code-execution state.
            self.messages.append({"role": "assistant", "content": message.content})
            if message.container is not None:
                self.container_id = message.container.id
            self._download_files(message, listener)
            if message.stop_reason == "pause_turn":
                listener.text("\n\n")  # a paused turn resumes in a new text block
                continue
            if message.stop_reason == "tool_use":
                results = [self._run_tool(block, listener) for block in tool_uses]
                self.messages.append({"role": "user", "content": results})
                listener.text("\n\n")
                continue
            note = ("The answer was cut off because it reached the length limit."
                    if message.stop_reason == "max_tokens" else "")
            listener.finished(note)
            return
        listener.finished("Claude was still working when Py-Spread stopped waiting. "
                          "Ask it to continue if you want more.")

    def _stream_turn(self, listener: Listener):
        params = dict(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=self.messages,
            tools=self.tools,
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
                elif event.type == "content_block_start":
                    block_type = event.content_block.type
                    if block_type == "server_tool_use":
                        listener.status("Running code…")
                    elif block_type == "tool_use" and event.content_block.name == "write_cells":
                        listener.status("Preparing cells…")
            return stream.get_final_message()

    def _run_tool(self, block, listener: Listener) -> dict:
        """Run one of the sheet tools; its tool_result block."""
        if self.cancel_requested.is_set():
            raise _Cancelled
        try:
            content = self._tool_output(block, listener)
            return {"type": "tool_result", "tool_use_id": block.id, "content": content}
        except ToolInputError as e:
            return {"type": "tool_result", "tool_use_id": block.id, "content": str(e), "is_error": True}

    def _tool_output(self, block, listener: Listener) -> str:
        # Tool inputs streamed eagerly aren't validated by the API, so check
        # every field before using it.
        args = block.input
        if self.sheet is None or block.name not in ("read_cells", "write_cells"):
            raise ToolInputError(f"There's no tool named {block.name!r}.")
        if not isinstance(args, dict):
            raise ToolInputError("The input must be an object.")
        if block.name == "read_cells":
            if not isinstance(args.get("range"), str):
                raise ToolInputError("range must be a string such as A1:D20.")
            listener.status("Reading the sheet…")
            return listener.run_on_sheet(lambda: self.sheet.read(args["range"]))
        start, rows = args.get("start"), args.get("rows")
        if not isinstance(start, str):
            raise ToolInputError("start must be a cell name such as A1.")
        if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
            raise ToolInputError("rows must be a list of rows, each a list of cell values.")
        values = [[_cell_text(value) for value in row] for row in rows]
        listener.status("Writing to the sheet…")
        result = listener.run_on_sheet(lambda: self.sheet.write(start, values))
        listener.text(f"\n\n*{result.splitlines()[0]} Undo with ⌘Z.*\n\n")
        return result

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

    def _settle(self, asked_at: int, reason: str) -> None:
        """Leave the conversation ready for the next question after this one
        stopped early: drop the question if nothing answered it, and answer
        any tool calls left hanging, which the API requires."""
        if len(self.messages) == asked_at + 1:
            self.messages.pop()
            return
        last = self.messages[-1] if self.messages else None
        if last and last["role"] == "assistant":
            pending = [block for block in last["content"] if getattr(block, "type", None) == "tool_use"]
            if pending:
                self.messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": block.id, "content": reason, "is_error": True}
                    for block in pending
                ]})


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
