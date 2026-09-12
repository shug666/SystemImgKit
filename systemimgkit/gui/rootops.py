"""GUI-side caller for the root helper subprocess.

The GUI runs as a normal user. Operations needing root (unpack, pack) are
delegated to `systemimgkit.root_helper`, launched with a single `pkexec`
call. This module runs that subprocess, streams its stderr progress to the
GUI log panel, and parses the `SIK_RESULT`/`SIK_ERROR` protocol line from
stdout.

Unlike `runner.run()` (which merges stdout+stderr), here the two streams are
kept separate: stdout carries only `SIK_` protocol lines, stderr carries
progress (and pkexec's GLib warnings, harmless). This separation is what lets
us reliably extract the structured result despite pkexec noise.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading

from ..runner import CancelledError, cancel_debug


def _helper_module() -> list[str]:
    """Command to invoke the root helper as a module."""
    return [sys.executable, "-m", "systemimgkit.root_helper"]


def _run_helper(cmd_args: list[str], on_line, cancel) -> dict:
    """Run `pkexec <helper> <cmd_args...>`, return parsed result dict.

    Returns {"ok": True, ...fields} on success, {"ok": False, "error": ...}
    on failure (pkexec rejected / non-zero exit / helper crash). Raises
    CancelledError on cancel so the Worker surfaces "已取消" (not a failure
    dialog).

    Cancellation: the GUI is a normal user and the helper runs as root (via
    pkexec), so the GUI cannot signal it (SIGTERM/SIGKILL → EPERM). The helper
    sends its pid/pgid at startup (SIK_PID protocol line); on cancel the GUI
    spawns `pkexec kill -9 -<pgid>` — a second, brief authorization that kills
    the helper's whole process group (mke2fs/e2fsdroid included) as root.
    """
    full_cmd = ["pkexec"] + _helper_module() + cmd_args
    cancel_debug("rootops._run_helper: launching %s" % " ".join(full_cmd))
    try:
        proc = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        cancel_debug("rootops: pkexec not found")
        return {"ok": False, "error": "pkexec not found; cannot elevate to root"}
    cancel_debug("rootops: pkexec proc pid=%d" % proc.pid)

    # The helper's pid/pgid, captured from its SIK_PID protocol line. Shared
    # with the cancel watcher so it can authorize-kill the group on cancel.
    helper_pid = {"pid": None, "pgid": None}

    # reader thread: stderr → on_line (progress + pkexec GLib noise)
    def _drain_stderr():
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip("\n")
            if on_line and line:
                on_line(line)

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    # Cancellation watcher: when cancel is requested, spawn a second pkexec
    # that kills the helper's process group as root. The GUI can't signal the
    # root helper directly (EPERM), so this re-authorization is the kill path.
    def _watch_cancel():
        if cancel is None:
            cancel_debug("rootops._watch_cancel: cancel is None, watcher idle")
            return
        cancel_debug("rootops._watch_cancel: thread started, polling")
        import time as _t
        while proc.poll() is None:
            if cancel.cancelled:
                pgid = helper_pid["pgid"]
                cancel_debug("rootops._watch_cancel: CANCEL detected, helper pgid=%s" % pgid)
                if on_line:
                    on_line("正在终止后台进程（将弹出授权窗口）…")
                if pgid is not None:
                    # Spawn `pkexec kill -9 -<pgid>`: a second brief authorization
                    # that kills the helper's whole process group as root.
                    kill_cmd = ["pkexec", "kill", "-9", "-" + str(pgid)]
                    cancel_debug("rootops._watch_cancel: running %s" % " ".join(kill_cmd))
                    try:
                        kr = subprocess.run(kill_cmd, capture_output=True, text=True, timeout=30)
                        cancel_debug("rootops._watch_cancel: kill rc=%s out=%r err=%r"
                                     % (kr.returncode, kr.stdout, kr.stderr))
                    except subprocess.TimeoutExpired:
                        cancel_debug("rootops._watch_cancel: kill TIMED OUT")
                    except OSError as e:
                        cancel_debug("rootops._watch_cancel: kill FAILED: %s" % e)
                else:
                    cancel_debug("rootops._watch_cancel: no helper pgid yet, falling back to best-effort signal")
                # Best-effort direct signal (usually EPERM, harmless to try).
                try:
                    proc.terminate()
                except OSError:
                    pass
                return
            _t.sleep(0.1)
        cancel_debug("rootops._watch_cancel: proc already exited (poll!=None) before cancel, rc=%s" % proc.returncode)

    tc = threading.Thread(target=_watch_cancel, daemon=True)
    tc.start()

    # read stdout (protocol lines) in this thread; capture SIK_PID as it arrives
    protocol_lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        protocol_lines.append(line)
        if line.startswith("SIK_PID "):
            try:
                pid_info = json.loads(line[len("SIK_PID "):])
                helper_pid["pid"] = pid_info.get("pid")
                helper_pid["pgid"] = pid_info.get("pgid")
                cancel_debug("rootops: captured helper pid=%s pgid=%s"
                             % (helper_pid["pid"], helper_pid["pgid"]))
            except json.JSONDecodeError:
                pass

    proc.wait()
    cancel_debug("rootops: proc.wait() returned, rc=%s" % proc.returncode)
    t.join(timeout=2)
    tc.join(timeout=2)

    if cancel and cancel.cancelled:
        cancel_debug("rootops: cancel was set, raising CancelledError")
        # Raise so Worker emits the `cancelled` signal → "已取消" log, NOT a
        # failure dialog. Returning a failure dict here used to route cancel
        # through _on_packed → "打包失败: cancelled", which read as "broken".
        raise CancelledError("cancelled")

    # find the last SIK_RESULT / SIK_ERROR line (search from the end)
    for line in reversed(protocol_lines):
        if line.startswith("SIK_RESULT "):
            try:
                payload = json.loads(line[len("SIK_RESULT "):])
                payload["ok"] = True
                return payload
            except json.JSONDecodeError:
                break
        if line.startswith("SIK_ERROR "):
            try:
                return json.loads(line[len("SIK_ERROR "):])
            except json.JSONDecodeError:
                break

    # no protocol line → failure (pkexec rejected, helper crashed, etc.)
    rc = proc.returncode
    if rc == 126 or rc == 127:
        return {"ok": False, "error": "授权被拒绝或 pkexec 不可用(返回码 %d)" % rc}
    return {"ok": False, "error": "root helper 异常退出(返回码 %s)" % rc}


def run_unpack(image: str, workspace: str, *, on_line=None, cancel=None) -> dict:
    """Unpack via the root helper. `on_line`/`cancel` mirror the Worker API."""
    orig_uid = os.getuid()
    args = ["unpack", image, workspace, "--orig-uid", str(orig_uid)]
    return _run_helper(args, on_line, cancel)


def run_pack(workspace: str, output: str, *, deletions_file: str | None = None,
              sparse: bool = False, vbmeta: str | None = None,
              target_blocks: int | None = None,
              on_line=None, cancel=None) -> dict:
    """Pack via the root helper."""
    orig_uid = os.getuid()
    args = ["pack", workspace, output, "--orig-uid", str(orig_uid)]
    if deletions_file:
        args += ["--deletions", deletions_file]
    if sparse:
        args += ["--sparse"]
    if vbmeta:
        args += ["--vbmeta", vbmeta]
    if target_blocks:
        args += ["--target-blocks", str(target_blocks)]
    return _run_helper(args, on_line, cancel)
