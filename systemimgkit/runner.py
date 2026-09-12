"""Subprocess runner with line-by-line progress callbacks and cancellation.

Shared by the CLI and the PySide6 QThread workers so progress reporting is
consistent. Long operations (rsync, mke2fs, e2fsck) stream their stderr/stdout
line by line; a caller-supplied callback receives each line and can update a
progress bar or print to stdout.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Sequence

ProgressCallback = Callable[[str], None]

# ---- pack heartbeat (shared by root_helper producer & controller consumer) ----
#
# `mke2fs -d` / `e2fsdroid` emit no percentage during the file-population phase
# (the longest pack step), so the log otherwise appears frozen for minutes.
# A watcher thread in `root_helper` polls the output image's `st_blocks` (real
# allocated bytes, which grow as data is written) ~once per interval and emits
# a `\r`-prefixed heartbeat line carrying this sentinel. The controller renders
# any `\r` line whose prior line carries the sentinel as an in-place rolling
# update (one line for the whole fill), mirroring how rsync progress2 is shown.
# The percentage is an approximate proxy from real `st_blocks` growth (see
# change pack-progress-heartbeat, design D3), never a fabricated timer.
HEARTBEAT_INTERVAL_S = 0.8
HEARTBEAT_SENTINEL = "⟳"

# ---- cancel-path debug log -------------------------------------------------
# Writes a timestamped trace of the cancel lifecycle to a fixed file so a user
# can send it back when "取消" doesn't stop the backend. The root helper runs
# as root, so the path is world-writable (/tmp). Enable by setting
# SIK_CANCEL_DEBUG=1 (off by default to avoid clutter in normal use).
import time as _time
import os as _os
import threading as _threading
_CANCEL_DEBUG_LOG = "/tmp/sik_cancel_debug.log"
_CANCEL_LOCK = _threading.Lock()


def cancel_debug(msg: str) -> None:
    """Append a timestamped line to the cancel-path debug log if enabled.

    Called from the GUI (controller/rootops, normal user) and the root helper
    (root) — both write the same /tmp file. Flushes immediately so the trace is
    visible even if the process is killed mid-cancel. Enable by setting
    SIK_CANCEL_DEBUG=1 (off by default to avoid clutter in normal use).
    """
    if _os.environ.get("SIK_CANCEL_DEBUG") != "1":
        return
    try:
        line = "%.3f [%d] %s\n" % (_time.time(), _os.getpid(), msg)
        with _CANCEL_LOCK:
            with open(_CANCEL_DEBUG_LOG, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
    except OSError:
        pass


@dataclass
class RunResult:
    cmd: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    lines: list[str] = field(default_factory=list)


class CancelledError(Exception):
    """Raised when a run is cancelled via the cancel flag."""


class CancelToken:
    """A simple cooperative cancellation flag."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


def run(
    cmd: Sequence[str],
    *,
    on_line: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
    check: bool = True,
    input_text: str | None = None,
    capture: bool = True,
) -> RunResult:
    """Run a command, streaming output line by line to `on_line`.

    The command runs with stdout+stderr merged (stderr=STDOUT) so callers see a
    single ordered stream. If `cancel` is set, the process is terminated and
    CancelledError is raised.
    """
    if cancel and cancel.cancelled:
        raise CancelledError("cancelled before start")

    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    if input_text is not None and proc.stdin is not None:
        proc.stdin.write(input_text)
        proc.stdin.close()

    out_buf: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        if cancel and cancel.cancelled:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise CancelledError("cancelled: " + " ".join(map(shlex.quote, cmd)))
        line = line.rstrip("\n")
        lines.append(line)
        if on_line:
            on_line(line)
        if capture:
            out_buf.append(line)
    proc.wait()
    combined = "\n".join(out_buf)
    result = RunResult(cmd=list(cmd), returncode=proc.returncode, stdout=combined, stderr="", lines=lines)
    if check and proc.returncode != 0:
        from .errors import SystemImgKitError
        raise SystemImgKitError(
            f"command failed (rc={proc.returncode}): {' '.join(map(shlex.quote, cmd))}\n{combined}"
        )
    return result


def have_root() -> bool:
    """True if the current process can mount (euid 0 or CAP_SYS_ADMIN)."""
    import os
    return os.geteuid() == 0


def privilege_wrapper() -> list[str] | None:
    """Return a prefix command to gain root for the mount step, or None.

    Prefers running directly if we already have root; else prefers pkexec, then
    sudo -n (non-interactive). Returns None if no privilege escalation is
    available.

    Honors SIK_NO_ELEVATE=1 (set after the user declines startup elevation):
    returns None so per-command escalation windows don't keep popping up.
    """
    import os
    import shutil
    if have_root():
        return []
    if os.environ.get("SIK_NO_ELEVATE"):
        return None
    if shutil.which("pkexec"):
        return ["pkexec"]
    if shutil.which("sudo"):
        return ["sudo", "-n"]
    return None
