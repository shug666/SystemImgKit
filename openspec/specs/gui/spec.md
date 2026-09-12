## Requirements

### Requirement: Pack log shows real progress during the silent image-fill phase
The image-build step (`mke2fs -d` on the standard path, `mke2fs` + `e2fsdroid` on the shared_blocks path) emits no percentage during file population, which is the longest pack phase. The GUI SHALL surface a rolling heartbeat line during this phase reflecting the **real allocated bytes written** to the output image (from `st_blocks`), updated roughly once per second, so the log does not appear frozen for minutes. The heartbeat line SHALL render in place (one rolling line for the whole fill, not an appended line per tick). Any percentage shown SHALL be explicitly framed as approximate ("约 NN%") and derived from real `st_blocks` growth against the known target image size — never a fake time-based or synthetic percentage. The existing `indeterminate` progress bar SHALL be retained; no determinate/fake percentage bar is introduced. When the manifest cannot be loaded, the heartbeat SHALL report real bytes written without a percentage rather than invent one.

#### Scenario: Rolling heartbeat during the silent fill
- **WHEN** pack is in the `mke2fs -d` / `e2fsdroid` file-population phase
- **THEN** the log shows a single rolling line ("⟳ 正在构建镜像… 已写入 N GB (约 NN%)") that updates roughly once per second with the real allocated bytes, and does not append a new line per tick

#### Scenario: Output file not yet created
- **WHEN** the watcher ticks before `mke2fs` has created the output image (or after it was removed for a retry)
- **THEN** the watcher emits nothing for that tick rather than erroring, and resumes once the file exists and is growing

#### Scenario: Approximate percentage is not authoritative
- **WHEN** the heartbeat shows "约 NN%"
- **THEN** the percentage is derived from real `st_blocks` growth against the target image size and is explicitly framed as approximate, because `st_blocks` is non-linear (metadata/组表 written first; sparse/zero regions do not advance) and path-dependent

#### Scenario: Manifest unavailable
- **WHEN** the manifest cannot be loaded to compute the target image size
- **THEN** the heartbeat reports only real bytes written ("已写入 N GB") and omits the percentage, rather than showing a fabricated percentage

#### Scenario: Watcher does not outlive the pack call
- **WHEN** `pack.pack()` returns or the operation is cancelled
- **THEN** the heartbeat watcher stops promptly and emits no further lines, so it cannot interleave into the next operation's log

### Requirement: Metadata restore shows real i/N progress
The post-build metadata restore loop (standard mount-based path) iterates over manifest entries setting uid/gid/mode/xattrs/SELinux/caps. For large manifests this is itself a long, silent stretch. The GUI SHALL show a real `i/N` progress line (entries processed / total entries) during this loop, throttled to a bounded number of updates (e.g. every ~1000 entries), rendering in place. This ratio is exact (unlike the fill-phase percentage). The shared_blocks path, which applies metadata during `e2fsdroid` population rather than this loop, is unaffected.

#### Scenario: Large manifest metadata restore
- **WHEN** `_restore_metadata` runs over many entries
- **THEN** the log shows a rolling "⟳ 元数据回写 i/N" line updating at bounded granularity, reflecting the exact ratio of processed to total entries

#### Scenario: Small manifest
- **WHEN** the manifest has only a few thousand entries
- **THEN** the metadata heartbeat produces only a handful of updates and does not spam the log

#### Scenario: shared_blocks path unaffected
- **WHEN** the source image uses shared_blocks (metadata applied via `e2fsdroid -C/-S` during population)
- **THEN** no mount-based metadata restore loop runs and no `i/N` heartbeat is emitted for it

### Requirement: Cancel reliably terminates a running operation
Clicking "取消" during a long operation SHALL promptly terminate the backend work (including any root-owned `mke2fs`/`e2fsdroid`/`rsync`/`losetup` child) and SHALL surface a graceful "已取消" state, not a failure dialog. Because the backend runs under `pkexec` (which does not forward signals to the helper it launches, and the helper `setsid`s its own process group), the GUI cannot signal the root helper directly (EPERM); on cancel the GUI SHALL spawn a second brief `pkexec` authorization that kills the helper's process group as root. The helper SHALL also self-terminate when it detects its parent (pkexec) has died — by watching its parent pid change — as defense-in-depth. The helper's termination SHALL kill its whole process group (taking down any child it spawned) and then force-exit, without signal-handler self-recursion.

#### Scenario: Cancel during pack fill
- **WHEN** the user clicks "取消" while `mke2fs -d` / `e2fsdroid` is filling the image
- **THEN** the GUI spawns a re-authorized `pkexec kill` that kills the helper's process group (including the fill child), and the GUI shows "已取消。" — no "打包失败" error dialog

#### Scenario: No orphaned root process after cancel
- **WHEN** the cancel kills the helper's process group
- **THEN** no mke2fs/e2fsdroid/rsync child keeps running in the background — the whole group is torn down as root

#### Scenario: Signal handler does not recurse
- **WHEN** the helper receives SIGTERM/SIGINT (or the parent-watcher triggers the same path)
- **THEN** the terminate routine uses a re-entry guard and ends with a force-exit, so `killpg`-on-own-group cannot re-enter the handler and recurse

#### Scenario: Non-cancel failures still surface as errors
- **WHEN** the helper fails for a real reason (pkexec rejected rc 126/127, helper crashed, non-zero exit) and cancel was NOT requested
- **THEN** the controller surfaces the real error message (not "已取消")

### Requirement: Busy-state control embeds cancel in the progress bar
The cancel control and the busy progress indicator SHALL be presented as ONE fused element: an indeterminate progress bar with the cancel button embedded in its center (overlaid), shown only while an operation is in progress. This replaces the previously stacked separate cancel button + progress bar. The cancel pill is transparent at rest (so the progress bar reads as one uninterrupted strip) and shows a danger-colored fill on hover. Both remain gated on the busy state.

#### Scenario: Embedded cancel appears during an operation
- **WHEN** an operation is running (`progressBusy`)
- **THEN** one element shows the indeterminate progress bar with a transparent "取消" pill overlaid in its center; on hover the pill fills with the danger color

#### Scenario: Embedded control hidden when idle
- **WHEN** no operation is running
- **THEN** the embedded cancel+progress control is not visible

### Requirement: Cancel click gives immediate feedback
Clicking cancel SHALL immediately surface a "正在取消…" log line so the click is never perceived as "无反应", before the backend teardown (which follows within ~1 s) completes and the "已取消。" state is shown.

#### Scenario: Instant feedback on cancel
- **WHEN** the user clicks cancel while an operation is running
- **THEN** "正在取消…" appears in the log immediately, followed by "已取消。" once the backend has terminated
