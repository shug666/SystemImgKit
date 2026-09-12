## Why

During packing, the bottom log dock appears to jump from the first line
straight to "打包完成": nothing updates in between. The cause is not a
fake/buggy progress bar — the on-screen `ProgressBar` is already
`indeterminate` (an honest "busy" indicator) and the log lines emitted are
real stage labels. The real problem is that the **longest pack step emits
no output at all**:

- `pack.py` builds the ext4 image with `mke2fs -d` (standard path) or
  `mke2fs` + `e2fsdroid` (shared_blocks path). Both print only a few stage
  headers ("正在分配组表 / 写入 inode 表 / 将文件复制到设备") and then go
  **completely silent for the entire file-population phase** — the phase
  that dominates pack wall-time. `mke2fs -d` exposes no `--progress` flag
  and no percentage; this is a limitation of e2fsprogs, not the app.
- So the log parks on "mke2fs -d …" and does not move until the next stage
  ("restoring metadata…") finally prints, which reads as "stuck at the
  start, done only at the end".
- unpack does not have this problem because it uses `rsync --info=progress2`,
  which streams `\r`-rewritten progress lines the log already renders
  in-place. pack's bottleneck tool gives us no such stream.

A precise percentage is **not achievable** for the fill phase — `mke2fs -d`
does not report one and there is no supported way to extract it. But the
output image's **allocated blocks (`st_blocks`) grow as real data is
written**, which is a real, monotonic-ish signal that "work is happening".
Reporting that real byte count as a rolling heartbeat makes the log honest
(it reflects actual writing) and removes the "frozen at the start"
perception — without inventing a fake percentage.

## What Changes

- **Heartbeat watcher during the silent fill phase.** `root_helper` starts a
  daemon thread around the `pack.pack()` call that polls
  `os.stat(output_image).st_blocks` every ~0.8 s and emits a
  `\r`-prefixed heartbeat line ("正在构建镜像… 已写入 N GB / NN%") via the
  existing `_progress` channel. It reports a real allocated-byte count
  (and a *rough* percentage against the known target image size, clearly
  framed as approximate), and stops when `pack.pack()` returns. The
  percentage is derived from real `st_blocks` growth, not a fake timer.
- **In-place rolling render for heartbeat lines.** The controller's
  log-append logic today only rewrites a line in place when it matches the
  rsync `progress2` heuristic (`_looks_like_progress`). Heartbeat lines
  (Chinese text, no `%`/`/s`) would otherwise each append as a new line and
  spam the log. Extend the in-place rule to recognize a heartbeat
  sentinel prefix so successive heartbeats replace the previous one — one
  rolling line for the whole fill phase, mirroring how rsync progress is
  rendered today.
- **Real `i/N` progress for metadata restore.** `_restore_metadata` loops
  over manifest entries (`man.entries`) setting uid/gid/mode/xattrs. For
  large manifests this is itself a long, silent stretch. Emit
  `metadata i/N` every ~1000 entries (or via `\r`-rewrite) so it too shows
  real progress instead of a single "restoring metadata…" line that
  vanishes for minutes. Cheap for the common small manifest (6440 entries
  → ~6 lines), meaningful for large ones.
- **Keep the `indeterminate` progress bar.** It is honest and stays. No
  fake determinate bar is introduced.

### Non-goals
- No precise/authoritative percentage for the `mke2fs -d` fill — e2fsprogs
  does not provide one; the heartbeat percentage is an approximate
  proxy from `st_blocks`, clearly not authoritative.
- No change to pack internals, image format, AVB, CLI, or the backend size
  cap. No new subprocess; the watcher is an in-process `threading.Thread`
  inside `root_helper`.
- No progress display removed — the existing `indeterminate` bar and
  stage-log lines are kept; only the silent gap is filled with real signal.

## Capabilities

### Modified Capabilities
- `gui`: pack no longer presents a silent multi-minute gap in the log
  during `mke2fs -d` / `e2fsdroid` fill; a rolling heartbeat reports the
  real allocated bytes written (and an approximate percentage); metadata
  restore reports real `i/N` progress. No fake percentage is shown; the
  `indeterminate` progress bar is retained as-is.

## Impact

- **Code**:
  - `systemimgkit/root_helper.py` — start/stop a heartbeat watcher thread
    around the `_pack.pack()` call in `_cmd_pack`; poll `st_blocks`; emit
    `\r`-prefixed heartbeat lines; load the target image size (from the
    manifest block_count/block_size, same values pack uses) for the
    approximate percentage.
  - `systemimgkit/pack.py` — `_restore_metadata` emits `metadata i/N`
    progress through `on_line` (every ~1000 entries); optionally expose
    the chosen `build_block_count`/`block_size` so the watcher can compute
    target bytes without re-deriving them (or the watcher loads the
    manifest itself — see design D3).
  - `systemimgkit/gui/controller.py` — extend the in-place log-rewrite
    rule to recognize heartbeat lines (sentinel prefix) so they roll in
    place instead of appending; keep `_looks_like_progress` for rsync.
  - `systemimgkit/gui/qml/main.qml` — no change required (the log already
    renders `Controller.warnings`; heartbeat flows through the same
    path). The `indeterminate` `ProgressBar` is unchanged.
- **Risks**: the `st_blocks` proxy is non-linear (metadata/组表 written
  first, then linear fill; sparse/zero regions do not advance
  `st_blocks`) and differs between the standard and shared_blocks paths,
  so the percentage is approximate and may stall or jump — framed as
  approximate, never as authoritative. Polling `st_blocks` every ~0.8 s is
  negligible overhead. The watcher must robustly tolerate the output file
  not existing yet (pre-`mke2fs`) and being replaced/removed.
- **No breaking changes**: pure additive progress surfacing; CLI
  behavior is unchanged (the CLI calls `pack.pack()` directly; the
  heartbeat watcher lives in `root_helper`, so the CLI is unaffected —
  see design D2 for whether the CLI also benefits).
