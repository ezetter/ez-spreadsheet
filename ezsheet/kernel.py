"""Running notebook code in a Jupyter (IPython) kernel.

The kernel is a separate Python process, started the first time code runs, so
code that loops forever or crashes can't freeze or take down the spreadsheet.
It talks to the app over Unix domain sockets in a private temporary folder.
A worker thread starts it and runs queued cells one at a time; results come
back as Qt signals carrying Jupyter's output dicts.
"""

import atexit
import os
import queue
import shutil
import tempfile
import threading
import weakref
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

KERNEL_NAME = "python3"
START_TIMEOUT = 60  # seconds to wait for the kernel to start
POLL = 0.1  # seconds between checks for Stop or a dead kernel while code runs

_STOP = object()
_RESTART = object()


@dataclass
class _Evaluation:
    """A quiet question for the kernel: run `code`, then give `expression`'s value."""

    request_id: str
    code: str
    expression: str
_runners = weakref.WeakSet()  # shut down at exit, so no kernel process outlives the app


class KernelRunner(QObject):
    """Runs code cells in a kernel, in the order asked. Signals are emitted
    from the worker thread; Qt delivers them on the GUI thread."""

    state_changed = Signal(str)  # "starting", "idle", "busy", or "stopped"
    started = Signal(str, int)  # cell id, execution count: the cell began running
    output = Signal(str, dict)  # cell id, a Jupyter output dict
    finished = Signal(str, object, str)  # cell id, execution count, "ok"/"error"/"aborted"
    cancelled = Signal(str)  # cell id: taken off the queue without running
    failed = Signal(str)  # the kernel couldn't start; the message says why
    evaluated = Signal(str, object, str)  # request id, the value's repr (None if it failed), why it failed

    def __init__(self, parent=None, kernel_name: str = KERNEL_NAME):
        super().__init__(parent)
        self.kernel_name = kernel_name
        self.working_dir: str | None = None  # where the kernel starts (the sheet's folder)
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._manager = None
        self._client = None
        self._socket_dir = None
        _runners.add(self)

    # --- Called on the GUI thread ---

    def run(self, cell_id: str, code: str) -> None:
        """Queue a cell to run after any already queued."""
        self._ensure_thread()
        self._jobs.put((cell_id, code))

    def evaluate(self, request_id: str, code: str, expression: str) -> None:
        """After any queued cells, quietly run `code` and evaluate
        `expression` in the notebook's variables: no outputs, history, or run
        number. `evaluated` gives the value's repr. It never starts a kernel
        (one that isn't running has no variables to ask about)."""
        self._ensure_thread()
        self._jobs.put(_Evaluation(request_id, code, expression))

    def interrupt(self) -> None:
        """Stop the running cell (as Ctrl-C would) and drop the queued ones."""
        self._cancel_queued()
        manager = self._manager
        if manager is not None and manager.has_kernel:
            manager.interrupt_kernel()

    def restart(self) -> None:
        """Start a fresh kernel: every variable is forgotten."""
        self._cancel_queued()
        if self._manager is not None and self._manager.has_kernel:
            self._manager.interrupt_kernel()
        self._ensure_thread()
        self._jobs.put(_RESTART)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop the kernel process and the worker thread. The runner can be
        used again afterwards; it starts a new kernel when needed."""
        self._cancel_queued()
        thread = self._thread
        if thread is not None:
            self._stopping.set()
            self._jobs.put(_STOP)
            thread.join(timeout)
        self._stop_kernel()  # in case the thread didn't get to it
        self._thread = None
        self._stopping.clear()

    @property
    def has_kernel(self) -> bool:
        return self._manager is not None and self._manager.has_kernel

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stopping.clear()
            self._thread = threading.Thread(target=self._work, name="ezsheet-kernel", daemon=True)
            self._thread.start()

    def _cancel_queued(self) -> None:
        """Drop the queued cells and questions, keeping any queued Restart or Stop."""
        keep = []
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            if isinstance(job, tuple):
                self.cancelled.emit(job[0])
            elif isinstance(job, _Evaluation):
                self.evaluated.emit(job.request_id, None, "Python was stopped before it could answer.")
            else:
                keep.append(job)
        for job in keep:
            self._jobs.put(job)

    # --- The worker thread ---

    def _work(self) -> None:
        while True:
            job = self._jobs.get()
            if job is _STOP or self._stopping.is_set():
                break
            if job is _RESTART:
                self._stop_kernel()
                self._start_kernel()
                continue
            if isinstance(job, _Evaluation):
                self._evaluate(job)
                continue
            cell_id, code = job
            if not self._start_kernel():
                self.finished.emit(cell_id, None, "aborted")
                self._cancel_queued()
                continue
            status = self._execute(cell_id, code)
            if status != "ok":
                self._cancel_queued()  # like Jupyter's Run All: stop at the first error
        self._stop_kernel()

    def _start_kernel(self) -> bool:
        """Start the kernel if it isn't running; whether it is now."""
        if self._manager is not None and self._manager.is_alive():
            return True
        self._stop_kernel()
        self.state_changed.emit("starting")
        try:
            from jupyter_client import KernelManager

            self._socket_dir = tempfile.mkdtemp(prefix="ezsheet-kernel-")  # private: mode 0700
            self._manager = KernelManager(kernel_name=self.kernel_name, transport="ipc",
                                          ip=os.path.join(self._socket_dir, "kernel"))
            cwd = self.working_dir if self.working_dir and os.path.isdir(self.working_dir) else None
            self._manager.start_kernel(cwd=cwd)
            self._client = self._manager.client()
            self._client.start_channels()
            self._client.wait_for_ready(timeout=START_TIMEOUT)
        except Exception as e:  # noqa: BLE001 -- reported to the user
            self._stop_kernel()  # whatever part of it did start
            self.state_changed.emit("stopped")
            self.failed.emit(f"The Python kernel couldn't start: {e}")
            return False
        self.state_changed.emit("idle")
        return True

    def _execute(self, cell_id: str, code: str) -> str:
        client = self._client
        msg_id = client.execute(code, store_history=True, allow_stdin=False)
        self.state_changed.emit("busy")
        count = None
        while True:
            try:
                message = client.get_iopub_msg(timeout=POLL)
            except queue.Empty:
                if self._stopping.is_set():
                    return "aborted"
                if not self._manager.is_alive():
                    self.output.emit(cell_id, _error_output(
                        "KernelDied", "The Python kernel stopped. It will restart when you run a cell."))
                    self.finished.emit(cell_id, count, "error")
                    self.state_changed.emit("stopped")
                    return "error"
                continue
            if message["parent_header"].get("msg_id") != msg_id:
                continue
            kind, content = message["msg_type"], message["content"]
            if kind == "status":
                if content["execution_state"] == "idle":
                    break
            elif kind == "execute_input":
                count = content.get("execution_count")
                self.started.emit(cell_id, count)
            elif kind in ("stream", "display_data", "execute_result", "error", "clear_output"):
                self.output.emit(cell_id, _nbformat_output(kind, content))
        status = "ok"
        try:
            while True:  # the reply says whether the cell succeeded
                reply = client.get_shell_msg(timeout=5)
                if reply["parent_header"].get("msg_id") == msg_id:
                    status = reply["content"].get("status", "ok")
                    count = reply["content"].get("execution_count", count)
                    break
        except queue.Empty:
            pass
        self.finished.emit(cell_id, count, status)
        self.state_changed.emit("idle")
        return status

    def _evaluate(self, job: _Evaluation) -> None:
        if self._manager is None or not self._manager.is_alive():
            self.evaluated.emit(job.request_id, None, "Python isn't running.")
            return
        client = self._client
        msg_id = client.execute(job.code, silent=True, store_history=False, allow_stdin=False,
                                user_expressions={"value": job.expression})
        while True:  # the reply carries the value; nothing comes as output
            try:
                reply = client.get_shell_msg(timeout=POLL)
            except queue.Empty:
                if self._stopping.is_set():
                    self.evaluated.emit(job.request_id, None, "Python was stopped before it could answer.")
                    return
                if not self._manager.is_alive():
                    self.evaluated.emit(job.request_id, None, "Python stopped.")
                    self.state_changed.emit("stopped")
                    return
                continue
            if reply["parent_header"].get("msg_id") == msg_id:
                break
        content = reply["content"]
        value = content.get("user_expressions", {}).get("value", {}) if content.get("status") == "ok" else content
        if value.get("status") != "ok":
            self.evaluated.emit(job.request_id, None, f"{value.get('ename', 'Error')}: {value.get('evalue', '')}")
            return
        self.evaluated.emit(job.request_id, value.get("data", {}).get("text/plain"), "")

    def _stop_kernel(self) -> None:
        client, manager, socket_dir = self._client, self._manager, self._socket_dir
        self._client = self._manager = self._socket_dir = None
        if client is not None:
            try:
                client.stop_channels()
            except Exception:  # noqa: BLE001
                pass
        if manager is not None:
            try:
                manager.shutdown_kernel(now=True)
            except Exception:  # noqa: BLE001
                pass
        if socket_dir:
            shutil.rmtree(socket_dir, ignore_errors=True)


def _nbformat_output(kind: str, content: dict) -> dict:
    """A kernel message as a Jupyter notebook output dict."""
    if kind == "stream":
        return {"output_type": "stream", "name": content["name"], "text": content["text"]}
    if kind == "error":
        return {"output_type": "error", "ename": content["ename"], "evalue": content["evalue"],
                "traceback": content["traceback"]}
    if kind == "clear_output":
        return {"output_type": "clear_output"}
    output = {"output_type": kind, "data": content.get("data", {}), "metadata": content.get("metadata", {})}
    if kind == "execute_result":
        output["execution_count"] = content.get("execution_count")
    return output


def _error_output(name: str, message: str) -> dict:
    return {"output_type": "error", "ename": name, "evalue": message, "traceback": [f"{name}: {message}"]}


@atexit.register
def _shut_down_all() -> None:
    for runner in list(_runners):
        try:
            runner._stopping.set()
            runner._stop_kernel()
        except Exception:  # noqa: BLE001
            pass
