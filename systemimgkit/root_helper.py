"""Root helper subprocess for the SystemImgKit GUI.

This module is executed with root privileges via a single `pkexec` call from
the GUI (`gui/rootops.py`). The GUI itself runs as a normal user so the native
file dialog can reach the user's home; only the operations that need root
(unpack's loop mount + rsync, pack's metadata restore via in-process
`os.setxattr`) are delegated here, where the process *is* root and
`privilege_wrapper()` returns `[]` (commands run directly as root).

Protocol (so pkexec's GLib warnings on stderr can't corrupt the result):
  - stderr: one progress line each → the GUI forwards these to its log panel.
  - stdout: protocol lines only, each prefixed `SIK_`:
      `SIK_RESULT <json>`  — success, JSON carries the result fields.
      `SIK_ERROR  <json>`  — failure, JSON has `error` and `traceback`.
  - exit code 0 = success, non-zero = failure.

Usage:
  python -m systemimgkit.root_helper unpack <image> <workspace> --orig-uid <N>
  python -m systemimgkit.root_helper pack   <workspace> <output> --orig-uid <N>
            [--deletions <file>] [--sparse] [--vbmeta <path>]

The helper never imports PySide6, so it runs headless under pkexec.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import signal
import subprocess
import sys
import threading
import time
import traceback

from .runner import HEARTBEAT_INTERVAL_S, HEARTBEAT_SENTINEL, cancel_debug


# ---- output helpers ---------------------------------------------------------

def _progress(line: str) -> None:
    """Emit a progress line on stderr (GUI forwards these to the log panel)."""
    print(line, file=sys.stderr, flush=True)


def _emit_result(payload: dict) -> None:
    print("SIK_RESULT " + json.dumps(payload), flush=True)


def _emit_error(message: str, tb: str = "") -> None:
    print("SIK_ERROR " + json.dumps({"ok": False, "error": message, "traceback": tb}),
          flush=True)


def _emit_pid() -> None:
    """Emit our pid + pgid right at startup so the GUI can authorize-kill us
    on cancel (the GUI is a normal user and can't signal this root process)."""
    print("SIK_PID " + json.dumps({"pid": os.getpid(), "pgid": os.getpgid(0)}),
          flush=True)


# ---- pack heartbeat ---------------------------------------------------------
#
# `mke2fs -d` / `e2fsdroid` are silent during the file-population phase (the
# longest pack step), so the GUI log appears frozen for minutes. This watcher
# polls the output image's `st_blocks` (real allocated bytes, which grow as
# data is written) and emits a `\r`-prefixed heartbeat line roughly once per
# `HEARTBEAT_INTERVAL_S`. The controller renders it as an in-place rolling
# line (one line for the whole fill). The percentage is an approximate proxy
# from real `st_blocks` growth against the known target image size — never a
# fabricated timer (see change pack-progress-heartbeat, design D1/D3).
#
# Empirically (real shared_blocks system.img, 11.58 GB staging, 325 s fill)
# `st_blocks` grows monotonically 0 → ~94% of the apparent size (= the true
# fill ratio), with periodic ~5–10 s stalls during dedup/inode phases and a
# final plateau at the fill ratio before exit. `e2fsck -fy` does not change it.

class _Heartbeat:
    """Background watcher that emits a rolling "正在构建镜像…" heartbeat.

    Started just before `pack.pack()` and stopped just after it returns (or on
    cancel). Runs as a daemon thread so it never strands the helper if the main
    thread dies; the stop `Event` guarantees it emits nothing after the pack
    call, so it can't interleave into the next operation's log.
    """

    def __init__(self, output_path, target_bytes, stop, cancel=None,
                 interval=HEARTBEAT_INTERVAL_S):
        self._output = output_path
        self._target_bytes = target_bytes      # None → bytes-only (no %)
        self._stop = stop
        self._cancel = cancel
        self._interval = interval
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def join(self, timeout=None):
        self._thread.join(timeout)

    def _run(self):
        while not self._stop.is_set():
            if self._cancel is not None and self._cancel.cancelled:
                return
            # poll real allocated bytes; the file may not exist yet (pre-mke2fs)
            # or may have been removed for a retry — skip the tick, don't crash.
            try:
                st = os.stat(self._output)
            except OSError:
                self._stop.wait(self._interval)
                continue
            written = st.st_blocks * 512
            line = f"\r{HEARTBEAT_SENTINEL} 正在构建镜像… 已写入 {written / 1e9:.2f} GB"
            if self._target_bytes:
                pct = min(100.0, 100.0 * written / self._target_bytes)
                line += f"  (约 {pct:.0f}%)"
            _progress(line)
            self._stop.wait(self._interval)


# ---- cancellation -----------------------------------------------------------

class _CancelToken:
    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


_CANCEL = _CancelToken()

# Re-entry guard for _terminate_cancel: os.killpg on our own group sends
# SIGTERM to ourselves too, which would re-enter _on_signal and recurse.
_TERMINATING = False


def _terminate_cancel() -> None:
    """Cancel the in-flight operation, tear down our process group, and exit.

    pkexec does NOT forward signals to the helper it launches, and we run in
    our own session (setsid), so the only reliable way to stop a runaway
    mke2fs/e2fsdroid/rsync/losetup child when the user cancels is for us to
    notice and kill our whole process group ourselves. We SIGTERM the group
    (children get a chance to clean up), then SIGKILL it so a stubborn
    mke2fs/e2fsdroid that ignores or stalls on SIGTERM is force-stopped; then
    os._exit so we run no more Python (loop_mount `finally` is skipped —
    leftover mounts are cleaned by _cleanup_stale on the next helper start).

    Guarded against re-entry: the group signals we send land on ourselves,
    which would re-enter _on_signal → _terminate_cancel → recursion. The
    _TERMINATING flag breaks that, and os._exit skips further signal delivery.
    """
    global _TERMINATING
    cancel_debug("helper _terminate_cancel: ENTER (guard=%s)" % _TERMINATING)
    if _TERMINATING:
        cancel_debug("helper _terminate_cancel: already terminating, skip")
        return
    _TERMINATING = True
    _CANCEL.cancel()
    try:
        pgid = os.getpgid(0)
        cancel_debug("helper _terminate_cancel: killpg SIGTERM pgid=%d" % pgid)
        os.killpg(pgid, signal.SIGTERM)
        cancel_debug("helper _terminate_cancel: killpg SIGKILL pgid=%d" % pgid)
        os.killpg(pgid, signal.SIGKILL)
    except OSError as e:
        cancel_debug("helper _terminate_cancel: killpg FAILED: %s" % e)
    cancel_debug("helper _terminate_cancel: os._exit(130)")
    os._exit(130)  # 128 + SIGTERM


def _on_signal(signum, _frame) -> None:
    """SIGTERM/SIGINT (cancel, or our own group-kill) → terminate the helper.

    We run in a new session (setsid), so killing our process group tears down
    any losetup/mount/rsync child we spawned. Delegates to _terminate_cancel,
    which is re-entry-safe (the group SIGTERM re-lands on us) and force-exits.
    """
    cancel_debug("helper _on_signal: received signal %d" % signum)
    _terminate_cancel()


def _watch_parent(initial_ppid: int) -> None:
    """Daemon thread: detect that our pkexec parent died and self-terminate.

    pkexec does not forward its signals to us, and we've setsid'd into our own
    process group, so if pkexec is killed (the GUI's cancel watcher terminates
    it) we'd otherwise be orphaned to init and keep running mke2fs at full
    load forever — the GUI, a normal user, can't signal our root group. Poll
    getppid() ~every 0.5 s; any change (reparented to init/subreaper) means
    pkexec is gone → tear down and exit via _terminate_cancel.
    """
    cancel_debug("helper _watch_parent: thread started, initial_ppid=%d, my pid=%d, my ppid=%d"
                 % (initial_ppid, os.getpid(), os.getppid()))
    while not _TERMINATING:
        try:
            cur = os.getppid()
            if cur != initial_ppid:
                cancel_debug("helper _watch_parent: ppid changed %d -> %d, terminating"
                             % (initial_ppid, cur))
                _terminate_cancel()
                return
        except OSError:
            cancel_debug("helper _watch_parent: getppid OSError, exiting watcher")
            return
        time.sleep(0.5)
    cancel_debug("helper _watch_parent: loop exited (TERMINATING set)")


# ---- stale-mount cleanup (recovers from a previously-killed helper) -----------

def _cleanup_stale() -> None:
    """umount leftover sik_mount_* and detach orphaned loop devices."""
    try:
        with open("/proc/mounts", "r") as fh:
            mounts = [ln.split()[1] for ln in fh if "sik_mount_" in ln]
    except OSError:
        mounts = []
    for mp in mounts:
        subprocess.run(["umount", "-l", mp], check=False,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # detach orphaned loops pointing at sik work
    try:
        out = subprocess.run(["losetup", "-a"], check=False,
                              capture_output=True, text=True).stdout
    except OSError:
        out = ""
    for line in out.splitlines():
        # /dev/loopN: [...] (image-path)
        if "sik" in line.lower():
            dev = line.split(":", 1)[0].strip()
            if dev.startswith("/dev/loop"):
                subprocess.run(["losetup", "-d", dev], check=False,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---- ownership --------------------------------------------------------------

def _chown_tree(path: str, uid: int) -> None:
    """Recursively chown a tree to `uid` (helper is root; the normal user
    must own the extracted tree to delete/edit it later). Symlinks are not
    followed."""
    try:
        pwent = pwd.getpwuid(uid)
    except KeyError:
        return
    gid = pwent.pw_gid
    for dirpath, dirnames, filenames in os.walk(path):
        try:
            os.lchown(dirpath, uid, gid)
        except OSError:
            pass
        for name in dirnames + filenames:
            fp = os.path.join(dirpath, name)
            try:
                os.lchown(fp, uid, gid)
            except OSError:
                pass


# ---- subcommands ------------------------------------------------------------

def _cmd_unpack(args) -> int:
    from . import unpack as _unpack
    try:
        res = _unpack.unpack(
            args.image, args.workspace,
            on_line=_progress, cancel=_CANCEL, allow_rootless=True,
        )
        # chown the extracted tree + manifest to the original user
        if args.orig_uid is not None:
            _chown_tree(res.workspace.tree, args.orig_uid)
            try:
                os.lchown(res.workspace.manifest, args.orig_uid,
                          pwd.getpwuid(args.orig_uid).pw_gid)
            except (OSError, KeyError):
                pass
        _emit_result({
            "ok": True,
            "footer_stripped": res.footer_stripped,
            "original_image_size": res.original_image_size,
            "incomplete": res.incomplete,
            "source_size": res.source_size,
            "source_mtime": res.source_mtime,
            "app_count": res.app_count,
            "workspace": res.workspace.root,
        })
        return 0
    except Exception as e:  # noqa: BLE001
        _emit_error(f"{type(e).__name__}: {e}", traceback.format_exc())
        return 1


def _cmd_pack(args) -> int:
    from . import pack as _pack
    from .workspace import Workspace
    if args.orig_uid is not None:
        # pack._maybe_chown_to_user reads SIK_ORIG_UID to chown products back.
        os.environ["SIK_ORIG_UID"] = str(args.orig_uid)
    try:
        deletions = None
        if args.deletions:
            from . import catalog
            deletions = catalog.load_deletions(args.deletions)

        # Heartbeat target size: the image pack will build, in bytes. pack
        # sizes the output at (target_blocks or original_block_count) *
        # block_size; mirror that here so the percentage is against the same
        # ceiling pack uses. If the manifest cannot be loaded, fall back to
        # bytes-only (no %) — never a fabricated number.
        target_bytes = None
        try:
            from . import manifest
            man = manifest.Manifest.load(
                Workspace(root=args.workspace).manifest)
            block_size = man.block_size or 4096
            build_blocks = args.target_blocks or man.block_count or (
                man.original_image_size // block_size)
            if build_blocks:
                target_bytes = build_blocks * block_size
        except (OSError, ValueError):
            target_bytes = None

        stop = threading.Event()
        hb = _Heartbeat(args.output, target_bytes, stop, cancel=_CANCEL)
        hb.start()
        try:
            res = _pack.pack(
                Workspace(root=args.workspace),
                args.output,
                deletions=deletions,
                sparse=args.sparse,
                vbmeta_image=args.vbmeta,
                target_blocks=args.target_blocks,
                on_line=_progress, cancel=_CANCEL,
            )
        finally:
            stop.set()
            hb.join(timeout=2.0)
        _emit_result({
            "ok": True,
            "output_image": res.output_image,
            "sparse_image": res.sparse_image,
            "flash_script": res.flash_script,
            "block_count": res.block_count,
            "block_size": res.block_size,
            "e2fsck_clean": res.e2fsck_clean,
            "warnings": res.warnings,
            "metadata_restored": res.metadata_restored,
        })
        return 0
    except Exception as e:  # noqa: BLE001
        _emit_error(f"{type(e).__name__}: {e}", traceback.format_exc())
        return 1


# ---- entry ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    os.setsid()  # own process group → clean group-kill on cancel
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    cancel_debug("helper main: started, pid=%d ppid=%d pgid=%d args=%s"
                 % (os.getpid(), os.getppid(), os.getpgid(0), argv))
    # Send our pid/pgid to the GUI immediately so it can authorize-kill us on
    # cancel (the GUI is a normal user and can't signal this root process).
    _emit_pid()
    _cleanup_stale()
    # Watch our pkexec parent: if it dies (GUI cancel terminates pkexec) we
    # won't get a forwarded signal, so detect orphaning and self-terminate.
    threading.Thread(target=_watch_parent, args=(os.getppid(),),
                     daemon=True).start()

    p = argparse.ArgumentParser(prog="systemimgkit.root_helper")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("unpack")
    sp.add_argument("image")
    sp.add_argument("workspace")
    sp.add_argument("--orig-uid", type=int, default=None)
    sp.set_defaults(func=_cmd_unpack)

    sp = sub.add_parser("pack")
    sp.add_argument("workspace")
    sp.add_argument("output")
    sp.add_argument("--orig-uid", type=int, default=None)
    sp.add_argument("--deletions", default=None)
    sp.add_argument("--sparse", action="store_true")
    sp.add_argument("--vbmeta", default=None)
    sp.add_argument("--target-blocks", type=int, default=None,
                    dest="target_blocks")
    sp.set_defaults(func=_cmd_pack)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
