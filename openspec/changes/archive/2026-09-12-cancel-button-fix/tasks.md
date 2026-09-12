## 1. Backend: helper self-terminates when pkexec parent dies

- [x] 1.1 In `root_helper`, add a shared `_terminate_cancel()` that sets a re-entry guard, calls `_CANCEL.cancel()`, `os.killpg(os.getpgid(0), signal.SIGTERM)`, then `os._exit(130)` — so the group SIGTERM reaches children first and the process force-exits without handler recursion
- [x] 1.2 Rewrite `_on_signal` to call `_terminate_cancel()` (replace the inline killpg that self-recurses)
- [x] 1.3 Add a `_watch_parent` daemon thread: capture the initial `os.getppid()` at startup; poll ~every 0.5 s; if the ppid changes (pkexec died → reparented to init/subreaper), call `_terminate_cancel()`. Start it in `main()` after `os.setsid()`
- [x] 1.4 Guard `getppid`/`getpgid` against `OSError` (process already going down) so the watcher never crashes the helper

## 2. Backend: cancel routes through `cancelled`, not a failure dialog

- [x] 2.1 In `rootops._run_helper`, on cancel (`cancel.cancelled`) raise `CancelledError("cancelled")` instead of returning `{"ok": False, "error": "cancelled"}`, so `Worker.run()` emits the `cancelled` signal → `_on_worker_cancelled`
- [x] 2.2 Keep the non-cancel failure paths (rc 126/127, no protocol line, helper crash) returning their `{"ok": False, "error": ...}` dict so real errors still surface via `_on_packed`/`_on_unpacked`
- [x] 2.3 In `_watch_cancel`, after `proc.terminate()`, escalate to `proc.kill()` if the process hasn't exited within ~3 s (defensive backstop; the helper parent-watcher is the real guarantee)

## 3. UI: embed cancel button in the progress bar

- [x] 3.1 In `main.qml`, replace the stacked cancel-button `Loader` + `ProgressBar` (pipeCardCol) with ONE fused element shown only while `Controller.progressBusy`: an `indeterminate` `ProgressBar` with the cancel pill overlaid in its CENTER (embedded, not a side-by-side bar+button row)
- [x] 3.2 The cancel pill stays enabled only while `progressBusy` and its `onClicked` calls `Controller.cancelWorker()`; the bar does not swallow the pill's clicks (pill is z-above)
- [x] 3.3 Verify the embedded control is hidden when idle and the layout/spacing matches the card (no extra vertical gap vs. the old pair)
- [x] 3.4 `Controller.cancelWorker` emits "正在取消…" to the log immediately (before signalling the worker) so the click is never perceived as unresponsive

## 4. Tests & validation

- [x] 4.1 Unit test: `_terminate_cancel` re-entry guard prevents a second invocation from re-entering (mock `os._exit` to raise so the test can observe the guard and the single `killpg` call)
- [x] 4.2 Unit test: `_watch_parent` triggers `_terminate_cancel` when `getppid` changes from the captured initial value, and does not trigger while ppid is unchanged
- [x] 4.3 Unit test: `rootops._run_helper` with `cancel.cancelled` raises `CancelledError`; with a non-zero exit and no cancel returns the `{"ok": False, "error": ...}` dict (mock `subprocess.Popen`/polling)
- [x] 4.4 Unit test (controller): a `Worker` whose callable raises `CancelledError` emits `cancelled` and routes to `_on_worker_cancelled` (log "已取消。", no error dialog) — cover the cancel routing end-to-end
- [ ] 4.5 Manual smoke test: start a pack on a large image, click "取消" — the backend mke2fs/e2fsdroid stops promptly (no continued disk/CPU load), the log shows "已取消。" with no error dialog, and no orphaned root `mke2fs`/`e2fsdroid` process remains (`ps` / `pidof`)
