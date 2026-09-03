"""Background-job plumbing, kept independent of any UI toolkit.

The GUI runs one long job at a time — fetching a catalogue, generating thirty
PDFs, checking for updates — and every one of those is slow enough that the
window must stay responsive and the user must be able to give up partway. A
plain queue plus a cancel flag covers both, and unlike Qt signals it can be
tested without a display or an event loop.
"""

from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass


@dataclass
class Message:
    """One event from the worker thread back to the UI."""

    kind: str  # "catalog" | "preview" | "log" | "progress" | "status"
    #            "done" | "error" | "cancelled" | "report"
    payload: object = None


class Cancelled(Exception):
    """Raised inside a job when the user asks it to stop."""


class Worker:
    """Runs one background job at a time and reports through a queue."""

    def __init__(self) -> None:
        self.queue: "queue.Queue[Message]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def send(self, kind: str, payload: object = None) -> None:
        self.queue.put(Message(kind, payload))

    # ------------------------------------------------------------ cancelling

    def cancel(self) -> None:
        """Ask the running job to stop at its next checkpoint."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def raise_if_cancelled(self) -> None:
        """Checkpoint for use inside a job body."""
        if self._cancel.is_set():
            raise Cancelled()

    # --------------------------------------------------------------- running

    def start(self, fn, *args, **kwargs) -> bool:
        """Run ``fn`` on a background thread. False if one is already running."""
        if self.busy:
            return False
        self._cancel.clear()

        def run() -> None:
            try:
                fn(*args, **kwargs)
            except Cancelled:
                self.send("cancelled", None)
            except Exception as exc:  # noqa: BLE001 - surfaced in the UI
                self.send("error", f"{type(exc).__name__}: {exc}")
                self.send("log", traceback.format_exc())
            finally:
                self.send("done", None)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return True

    def drain(self, limit: int = 200) -> list[Message]:
        """Pop up to ``limit`` pending messages. Called from the UI thread.

        The limit keeps a chatty job from starving the event loop; whatever is
        left over arrives on the next tick.
        """
        out: list[Message] = []
        for _ in range(limit):
            try:
                out.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return out
