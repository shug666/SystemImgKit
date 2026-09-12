## MODIFIED Requirements

### Requirement: Cancel reliably terminates a running operation
Clicking "取消" during a long operation SHALL promptly terminate the backend
work (including any root-owned `mke2fs`/`e2fsdroid`/`rsync`/`losetup` child) and
SHALL surface a graceful "已取消" state, not a failure dialog. Because the
backend runs under `pkexec` (which does not forward signals to the helper it
launches, and the helper `setsid`s its own process group), the helper SHALL
self-terminate when it detects its parent (pkexec) has died — by watching its
parent pid change — so the cancel does not leave an orphaned root process
thrashing the disk after the GUI believes the operation was cancelled. The
helper's termination SHALL kill its whole process group (taking down any
child it spawned) and then force-exit, without signal-handler self-recursion.

#### Scenario: Cancel during pack fill
- **WHEN** the user clicks "取消" while `mke2fs -d` / `e2fsdroid` is filling
  the image
- **THEN** the GUI's cancel watcher terminates the pkexec process, the helper
  detects its parent died and kills its process group (including the fill
  child), and the GUI shows "已取消。" — no "打包失败" error dialog

#### Scenario: No orphaned root process after cancel
- **WHEN** the cancel terminates the pkexec parent
- **THEN** the helper (orphaned to init) detects its parent pid changed within
  ~0.5 s, cancels its `_CANCEL` token, kills its own process group, and exits
  — no mke2fs/e2fsdroid/rsync child keeps running in the background

#### Scenario: Signal handler does not recurse
- **WHEN** the helper receives SIGTERM/SIGINT (or the parent-watcher triggers
  the same path)
- **THEN** the terminate routine uses a re-entry guard and ends with a
  force-exit, so `killpg`-on-own-group cannot re-enter the handler and recurse

#### Scenario: Non-cancel failures still surface as errors
- **WHEN** the helper fails for a real reason (pkexec rejected rc 126/127,
  helper crashed, non-zero exit) and cancel was NOT requested
- **THEN** the controller surfaces the real error message (not "已取消")

### Requirement: Busy-state control embeds cancel in the progress bar
The cancel control and the busy progress indicator SHALL be presented as ONE
fused element: an indeterminate progress bar with the cancel button embedded
in its center (overlaid), shown only while an operation is in progress. This
replaces the previously stacked separate cancel button + progress bar (and the
side-by-side bar+button row). Both remain gated on the busy state.

#### Scenario: Embedded cancel appears during an operation
- **WHEN** an operation is running (`progressBusy`)
- **THEN** one element shows the indeterminate progress bar with an enabled
  cancel pill overlaid in its center

#### Scenario: Embedded control hidden when idle
- **WHEN** no operation is running
- **THEN** the embedded cancel+progress control is not visible

### Requirement: Cancel click gives immediate feedback
Clicking cancel SHALL immediately surface a "正在取消…" log line so the click
is never perceived as "无反应", before the backend teardown (which follows
within ~1 s) completes and the "已取消。" state is shown.

#### Scenario: Instant feedback on cancel
- **WHEN** the user clicks cancel while an operation is running
- **THEN** "正在取消…" appears in the log immediately, followed by "已取消。"
  once the backend has terminated
