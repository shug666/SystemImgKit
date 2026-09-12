## Why

The "取消" (cancel) button appears to do nothing. Two bugs combine to make
cancellation both misleading and ineffective:

1. **UI reports a failure, not a cancellation.** When the user clicks cancel,
   `rootops._run_helper` returns `{"ok": False, "error": "cancelled"}` as a
   *normal return value*. `Worker.run()` sees a returned dict (not a raised
   `CancelledError`) and emits `finished`, so the controller routes to
   `_on_packed`/`_on_unpacked` → `ok` is False → it pops a **"打包失败:
   cancelled" / "解包失败: cancelled" error dialog** instead of the
   graceful "已取消" log line. To the user the button "doesn't work": it
   either looks like a failure or, worse, looks like nothing happened.

2. **The backend keeps running after cancel — the real cause.** `proc.terminate()`
   in `_watch_cancel` sends SIGTERM to **pkexec only**. pkexec does not forward
   signals to the helper it launched, and the helper called `os.setsid()` in
   `main()`, so it lives in its own process group. When pkexec dies, the helper
   is **orphaned (reparented to init) and keeps running mke2fs/e2fsdroid at full
   load** — its SIGTERM handler never fires. The GUI is a normal user and
   cannot signal the root-owned orphan process group. Verified empirically:
   killing the pkexec-analog leaves the `setsid` child alive 5+ s later,
   having never received a signal. So even after the button is clicked, the
   disk-thrashing mke2fs continues — the cancel is cosmetic.

   **Root cause confirmed in the live GUI** (via `/tmp/sik_cancel_debug.log`):
   `proc.terminate()` / `proc.kill()` on the pkexec process return **EPERM
   ("不允许的操作")** — the GUI is a normal user and pkexec runs as **root**
   after polkit authorization, so the GUI has no permission to signal it. The
   pkexec process is never killed → the helper is never orphaned → the
   parent-watcher never fires → mke2fs runs to completion. Signaling the root
   pkexec from a normal-user GUI is fundamentally impossible; a different
   channel is required.

A secondary latent bug: `root_helper._on_signal` calls
`os.killpg(os.getpgid(0), SIGTERM)`, which signals **its own group including
itself**, re-entering the handler → `RecursionError` (observed in an isolated
repro). This would prevent a clean self-termination if the signal ever did
arrive.

## What Changes

- **Cancel via re-authorized root kill (the actual fix).** Since the GUI
  (normal user) cannot signal the root helper (EPERM), cancellation spawns a
  SECOND, brief `pkexec` authorization that kills the helper's process group
  as root. The helper emits its pid/pgid at startup (`SIK_PID` protocol line);
  `_run_helper` captures it. On cancel, `_watch_cancel` runs
  `pkexec kill -9 -<pgid>` — a polkit auth dialog pops, and once authorized
  the root `kill` tears down the helper's whole process group (mke2fs/
  e2fsdroid included). This is the user-chosen approach: re-authorize on
  cancel rather than a background channel. `proc.terminate()` is kept as a
  best-effort backstop (it EPERMs in practice but is harmless).
- **Parent-watcher retained as defense-in-depth.** `_watch_parent` still
  detects pkexec dying (ppid change) and self-terminates — useful if pkexec
  exits on its own.
- **Fix the signal handler self-recursion.** `_on_signal` (and the shared
  terminate path) sets a re-entry guard and ends with `os._exit(130)` so
  `killpg`-on-own-group cannot recurse; the group SIGTERM+SIGKILL still
  reaches children first.
- **Cancel routes through the `cancelled` signal.** `rootops._run_helper`
  raises `CancelledError` (already imported) on cancel instead of returning a
  failure dict, so `Worker.run()` emits `cancelled` →
  `_on_worker_cancelled` → the log shows "已取消。" and no error dialog. The
  existing non-cancel failure paths (pkexec rejected rc 126/127, helper crash)
  keep returning their dict so the real error is still surfaced.
- **Cancel button embedded in the progress bar.** The cancel control and the
  busy progress indicator are ONE fused element: an `indeterminate`
  `ProgressBar` with a compact "取消" pill overlaid in its center, shown only
  while `progressBusy`. Replaces the previously stacked separate button + bar.
- **Immediate feedback.** `cancelWorker` logs "正在取消…" at once so the
  click is never perceived as unresponsive.

### Non-goals
- No change to what operations are cancellable (all already route through
  `Worker`); only the termination reliability + UI routing/embed.
- No stdin/IPC protocol — the cancel channel is a single sentinel file in
  `/tmp`, polled by a daemon thread in the already-root helper.
- No change to the heartbeat/progress content; the embedded control reuses
  the existing `indeterminate` `ProgressBar`.

## Capabilities

### Modified Capabilities
- `gui`: clicking cancel during a long operation terminates the backend
  promptly (the root helper self-terminates when it detects the cancel
  sentinel file the GUI created; signaling the root pkexec is impossible
  from a normal user, so a file channel is used) and surfaces "已取消"
  without a failure dialog; the cancel button is embedded in the progress
  bar, shown only while busy.

## Impact

- **Code**:
  - `systemimgkit/root_helper.py` — add `_watch_cancel_file` daemon thread
    (started in `main` when `--cancel-file` is given); add `_watch_parent`
    (defense-in-depth); shared `_terminate_cancel()` (cancel + `killpg`
    SIGTERM+SIGKILL + `os._exit` with a re-entry guard); `_on_signal` calls
    it; new `--cancel-file` arg on both subcommands.
  - `systemimgkit/gui/rootops.py` — `_run_helper` allocates a `/tmp` cancel
    file, passes `--cancel-file`, creates it on cancel; raises
    `CancelledError` on cancel; `_watch_cancel` keeps `terminate()`/`kill()`
    as best-effort (EPERM in practice); `_cleanup_cancel_file` helper.
  - `systemimgkit/gui/qml/main.qml` — fused `ProgressBar` + centered cancel
    pill, `progressBusy`-gated; immediate "正在取消…" feedback.
  - `systemimgkit/runner.py` — `cancel_debug()` helper writing the
    `/tmp/sik_cancel_debug.log` trace across the user/root boundary
    (diagnostic for this issue; always-on while investigating).
- **Risks**: the cancel file lives in `/tmp` (world-writable); a stale file
  from a crashed run is harmless (helper polls *existence*, and
  `_cleanup_cancel_file` removes it after the run). A collision with another
  `sik_cancel_*.flag` is negligible (mkstemp random suffix). If `/tmp` is
  somehow unwritable the channel degrades to the best-effort signal path
  (which EPERMs) — but `/tmp` is standard. `os._exit` skips `loop_mount`'s
  `finally` umount, so a cancelled pack may leave a `sik_mount_*` mount;
  `_cleanup_stale` cleans these on the next helper start — acceptable, and
  `killpg` takes the loop/mke2fs children down with it.
- **No breaking changes**: CLI is unaffected (no pkexec/worker layer); only
  the GUI cancel path changes, and it only becomes reliable.
