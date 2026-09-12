"""Unit tests: cancel-button-fix (tasks 4.1–4.4).

Covers:
- _terminate_cancel re-entry guard + single killpg (root_helper)
- _watch_parent triggers on ppid change (root_helper)
- _run_helper raises CancelledError on cancel, returns dict on real failure
  (rootops)
- Worker routes a CancelledError-raising callable to the `cancelled` signal
  (controller end-to-end)
"""

from __future__ import annotations

import signal
import threading

import pytest

from systemimgkit import root_helper
from systemimgkit.runner import CancelToken, CancelledError


# ---- 4.1: _terminate_cancel re-entry guard ----------------------------------

def test_terminate_cancel_reentry_guard(monkeypatch):
    """4.1: _terminate_cancel runs once — the group SIGTERM it sends would
    re-enter the handler; the guard prevents a second killpg, and os._exit
    is taken at the end."""
    calls = {"killpg": 0, "exit": 0, "cancel": 0}

    class FakeCancel:
        def cancel(self):
            calls["cancel"] += 1
    monkeypatch.setattr(root_helper, "_CANCEL", FakeCancel())

    def fake_killpg(pgid, sig):
        calls["killpg"] += 1
    monkeypatch.setattr(root_helper.os, "killpg", fake_killpg)
    monkeypatch.setattr(root_helper.os, "getpgid", lambda x: 123)

    # capture os._exit instead of actually exiting
    def fake_exit(code):
        calls["exit"] += 1
        raise SystemExit(code)
    monkeypatch.setattr(root_helper.os, "_exit", fake_exit)

    # reset the module guard (other tests may have flipped it)
    root_helper._TERMINATING = False

    with pytest.raises(SystemExit):
        root_helper._terminate_cancel()
    # a second invocation must be a no-op (guard)
    # (simulate the re-entering group signal by calling again; guard should
    # short-circuit without touching killpg/exit again)
    root_helper._terminate_cancel()

    assert calls["cancel"] == 1
    # SIGTERM then SIGKILL → two killpg calls, but only on the first (guarded) entry
    assert calls["killpg"] == 2
    assert calls["exit"] == 1


# ---- 4.2: _watch_parent triggers on ppid change ------------------------------

def test_watch_parent_triggers_on_ppid_change(monkeypatch):
    """4.2: when getppid changes from the captured initial value, the watcher
    calls _terminate_cancel; while unchanged, it does not."""
    state = {"ppid": 100, "terminated": False}
    monkeypatch.setattr(root_helper.os, "getppid", lambda: state["ppid"])

    def fake_terminate():
        state["terminated"] = True
        # stop the loop by flipping the guard
        root_helper._TERMINATING = True
    monkeypatch.setattr(root_helper, "_terminate_cancel", fake_terminate)

    root_helper._TERMINATING = False
    t = threading.Thread(target=root_helper._watch_parent, args=(100,), daemon=True)
    t.start()
    # let it poll once or twice unchanged (no terminate)
    import time
    time.sleep(0.15)
    assert state["terminated"] is False
    # now reparent → trigger
    state["ppid"] = 1
    t.join(timeout=2.0)
    assert state["terminated"] is True


def test_watch_parent_no_trigger_when_ppid_stable(monkeypatch):
    """4.2: ppid never changes → no terminate (within a short window)."""
    monkeypatch.setattr(root_helper.os, "getppid", lambda: 555)
    root_helper._TERMINATING = False
    t = threading.Thread(target=root_helper._watch_parent, args=(555,), daemon=True)
    t.start()
    import time
    time.sleep(0.25)
    assert root_helper._TERMINATING is False
    assert t.is_alive()
    # clean up
    root_helper._TERMINATING = True
    t.join(timeout=2.0)


# ---- 4.3: _run_helper cancel raises, failure returns dict --------------------

def _fake_proc(monkeypatch, *, returncode, stdout_lines, exits_on_terminate=True):
    """Install a fake subprocess.Popen used by rootops._run_helper."""
    import subprocess
    from systemimgkit.gui import rootops

    class _FakeStream:
        def __init__(self, lines):
            self._lines = list(lines)
        def __iter__(self):
            return iter(self._lines)
        def close(self):
            pass

    class _FakeProc:
        def __init__(self):
            self.pid = 99999
            self.stdout = _FakeStream(stdout_lines)
            self.stderr = _FakeStream([])
            self.returncode = returncode
            self._killed = False
        def wait(self, timeout=None):
            return self.returncode
        def poll(self):
            return self.returncode if self._killed else None
        def terminate(self):
            self._killed = True
            self.returncode = -15
        def kill(self):
            self._killed = True
            self.returncode = -9

    fake = _FakeProc()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: fake)
    return fake


def test_run_helper_raises_on_cancel(monkeypatch):
    """4.3: when cancel is set, _run_helper raises CancelledError (not a dict)."""
    _fake_proc(monkeypatch, returncode=-15, stdout_lines=[], exits_on_terminate=True)
    from systemimgkit.gui import rootops
    cancel = CancelToken()
    cancel.cancel()
    with pytest.raises(CancelledError):
        rootops._run_helper(["pack", "/ws", "/out"], on_line=None, cancel=cancel)


def test_run_helper_returns_dict_on_real_failure(monkeypatch):
    """4.3: a real helper crash (rc != 0, no cancel) returns a failure dict."""
    # no SIK_RESULT/SIK_ERROR line, non-zero exit, not 126/127
    _fake_proc(monkeypatch, returncode=1, stdout_lines=["some stderr noise"])
    from systemimgkit.gui import rootops
    res = rootops._run_helper(["pack", "/ws", "/out"], on_line=None, cancel=None)
    assert isinstance(res, dict)
    assert res["ok"] is False
    assert "返回码" in res["error"]


def test_run_helper_returns_dict_on_pkexec_rejected(monkeypatch):
    """4.3: pkexec rejected (rc 126) surfaces the auth-denied error."""
    _fake_proc(monkeypatch, returncode=126, stdout_lines=[])
    from systemimgkit.gui import rootops
    res = rootops._run_helper(["pack", "/ws", "/out"], on_line=None, cancel=None)
    assert res["ok"] is False
    assert "126" in res["error"]


# ---- 4.4: Worker routes CancelledError to the cancelled signal ---------------

def test_worker_cancelled_signal_emitted(qapp_module):
    """4.4: a Worker whose callable raises CancelledError emits `cancelled`,
    not `failed`/`finished` — so the controller shows "已取消" (no error
    dialog)."""
    from PySide6.QtCore import QCoreApplication
    from systemimgkit.gui.workers import Worker

    def fn(on_line, cancel):
        raise CancelledError("cancelled")

    w = Worker(fn)
    seen = {"progress": [], "finished": False, "failed": None, "cancelled": False}
    # Direct connection so the slot runs synchronously on emit (the worker
    # thread emits; we observe without needing a running event loop).
    from PySide6.QtCore import Qt
    w.signals.progress.connect(lambda l: seen["progress"].append(l), Qt.DirectConnection)
    w.signals.finished.connect(lambda r: seen.__setitem__("finished", r), Qt.DirectConnection)
    w.signals.failed.connect(lambda m: seen.__setitem__("failed", m), Qt.DirectConnection)
    w.signals.cancelled.connect(lambda: seen.__setitem__("cancelled", True), Qt.DirectConnection)
    w.start()
    w.wait(5000)
    # process any deferred deletes / posted events
    QCoreApplication.processEvents()
    assert seen["cancelled"] is True
    assert seen["failed"] is None
    assert seen["finished"] is False


@pytest.fixture(scope="module")
def qapp_module():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---- SIK_PID capture + pkexec-kill cancel channel ---------------------------

def test_emit_pid_sends_pid_and_pgid(monkeypatch):
    """The helper emits SIK_PID <json> with pid+pgid at startup."""
    import io, json as _json
    monkeypatch.setattr(root_helper.os, "getpid", lambda: 4242)
    monkeypatch.setattr(root_helper.os, "getpgid", lambda x: 4242)
    captured = []
    monkeypatch.setattr(root_helper.sys, "stdout", io.TextIOWrapper(
        io.BytesIO(), write_through=True, encoding="utf-8"))
    # capture print via a stub
    import builtins
    real_print = builtins.print
    def fake_print(*a, **k):
        captured.append(a[0] if a else "")
    monkeypatch.setattr(builtins, "print", fake_print)
    root_helper._emit_pid()
    line = captured[0]
    assert line.startswith("SIK_PID ")
    info = _json.loads(line[len("SIK_PID "):])
    assert info == {"pid": 4242, "pgid": 4242}


def test_run_helper_captures_sik_pid(monkeypatch):
    """_run_helper parses the SIK_PID line and stores pid/pgid so the cancel
    watcher can authorize-kill the group."""
    import subprocess
    from systemimgkit.gui import rootops
    sik_pid_line = 'SIK_PID {"pid": 777, "pgid": 777}'
    class _FakeStream:
        def __init__(self, lines): self._l = list(lines)
        def __iter__(self): return iter(self._l)
        def close(self): pass
    class _FakeProc:
        pid = 1
        stdout = _FakeStream([sik_pid_line])
        stderr = _FakeStream([])
        returncode = 0
        _killed = False
        def wait(self, timeout=None): return self.returncode
        def poll(self): return self.returncode if self._killed else None
        def terminate(self): self._killed = True
        def kill(self): self._killed = True
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProc())
    # no cancel → returns dict (no SIK_RESULT → failure dict, but we only care
    # that SIK_PID was parsed). Patch the result path to observe capture.
    captured = {}
    # we can't directly observe helper_pid; verify via the cancel path instead.
    res = rootops._run_helper(["pack", "/ws", "/out"], on_line=None, cancel=None)
    # no SIK_RESULT/SIK_ERROR → failure dict (expected); SIK_PID was consumed
    assert res["ok"] is False


def test_run_helper_pkexec_kill_on_cancel(monkeypatch):
    """On cancel, _run_helper spawns `pkexec kill -9 -<pgid>` (the re-auth
    kill path) using the pgid captured from SIK_PID."""
    import subprocess
    from systemimgkit.gui import rootops
    sik_pid_line = 'SIK_PID {"pid": 555, "pgid": 555}'
    kill_cmds = []
    class _FakeStream:
        def __init__(self, lines): self._l = list(lines)
        def __iter__(self): return iter(self._l)
        def close(self): pass
    class _FakeProc:
        pid = 1
        stdout = _FakeStream([sik_pid_line])
        stderr = _FakeStream([])
        returncode = -9
        _killed = False
        def wait(self, timeout=None): return self.returncode
        def poll(self): return self.returncode if self._killed else None
        def terminate(self): self._killed = True
        def kill(self): self._killed = True
    def fake_popen(cmd, *a, **k):
        return _FakeProc()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    def fake_run(cmd, **k):
        kill_cmds.append(cmd)
        class R:  # noqa: B903
            returncode = 0; stdout = ""; stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)
    cancel = CancelToken()
    # cancel must be detected AFTER SIK_PID is captured; set it via a thread
    import threading, time
    def set_cancel():
        time.sleep(0.1)
        cancel.cancel()
    threading.Thread(target=set_cancel, daemon=True).start()
    with pytest.raises(CancelledError):
        rootops._run_helper(["pack", "/ws", "/out"], on_line=lambda l: None, cancel=cancel)
    # the kill command targeted the captured pgid
    assert kill_cmds, "pkexec kill should have been invoked on cancel"
    assert kill_cmds[0] == ["pkexec", "kill", "-9", "-555"]

