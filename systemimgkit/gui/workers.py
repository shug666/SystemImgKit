"""QThread worker base wrapping subprocess-driven operations (Task 7.2).

A `Worker` runs a plain callable on a background thread. The callable receives
an `on_line` callback (for progress) and a `CancelToken`. Signals are emitted on
the main thread for progress, completion, failure, and cancellation, so the UI
stays responsive and can cancel a running operation.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

from ..runner import CancelToken, cancel_debug


class WorkerSignals(QObject):
    progress = Signal(str)
    finished = Signal(object)   # result of the callable, or None
    failed = Signal(str)        # error message
    cancelled = Signal()


class Worker(QThread):
    """Run `fn(on_line=..., cancel=...)` on a background thread.

    `fn` must accept `on_line` and `cancel` keyword arguments and return a value
    (or raise). Use `worker.cancel()` to request cancellation.

    On destruction the thread is requested to cancel and waited for, so the
    QThread is never destroyed while still running (which would crash the
    process — "QThread: Destroyed while thread is still running").
    """

    def __init__(self, fn: Callable[..., object], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn = fn
        self.signals = WorkerSignals()
        self._cancel = CancelToken()

    def cancel(self) -> None:
        cancel_debug("Worker.cancel() called — setting CancelToken")
        self._cancel.cancel()
        cancel_debug("Worker.cancel() CancelToken now: %s" % self._cancel.cancelled)

    def run(self) -> None:  # QThread entry point
        try:
            result = self._fn(on_line=self._emit_progress, cancel=self._cancel)
        except Exception as e:  # noqa: BLE001
            from ..runner import CancelledError
            if isinstance(e, CancelledError):
                self.signals.cancelled.emit()
            else:
                self.signals.failed.emit(f"{type(e).__name__}: {e}")
        else:
            self.signals.finished.emit(result)

    def _emit_progress(self, line: str) -> None:
        self.signals.progress.emit(line)

    def __del__(self) -> None:
        # Never let a QThread be destroyed while its run() is still executing.
        try:
            self._cancel.cancel()
            if self.isRunning():
                self.wait(5000)  # bound wait; cancel should unwind promptly
        except RuntimeError:
            # Underlying C++ object already deleted (e.g. app teardown) — safe.
            pass
