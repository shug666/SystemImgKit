## ADDED Requirements

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
