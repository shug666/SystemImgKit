## Context

This change fills the silent gap in the pack log. The data path today:

```
GUI controller.packTo() (controller.py:707)
  → _start_worker(rootops.run_pack(...))                 # QThread
      → rootops._run_helper(["pack", ...])                # pkexec subprocess
          → root_helper._cmd_pack(args)                   # runs AS ROOT
              → pack.pack(..., on_line=_progress, cancel=_CANCEL)
                  ├─ run(["cp","-al", tree, staging], on_line=...)   # instant
                  ├─ run([mke2fs -d ... output_image ...])           # ← SILENT fill
                  ├─ _restore_metadata(output_image, man, ...)       # ← silent loop
                  ├─ run([e2fsck -fy output_image])                  # prints Pass 1-5
                  └─ ...
              → _emit_result({...})
          stderr ("progress" lines) ──────────────────────────┐
                                                              ▼
GUI rootops._drain_stderr → on_line → controller._on_progress → _append_log_line
```

Key facts established by investigation:

- **`mke2fs -d` is silent during file population.** Verified empirically: it
  prints only stage headers ("正在分配组表 / 写入 inode 表 / 创建日志 / 将
  文件复制到设备"); the "将文件复制到设备" (copy files to device) phase — the
  long one — emits no percentage and no count. There is no `--progress`
  flag. `e2fsdroid` (shared_blocks path) is similarly silent during fill.
- **The output image's `st_blocks` grows during fill.** `mke2fs` pre-creates
  the image at full apparent size (sparse), then writes real data blocks as
  it populates. `os.stat(out).st_blocks * 512` tracks real allocated bytes,
  rising from ~metadata toward ~staging size. This is a real signal — but
  non-linear (metadata/组表 first; sparse/zero regions do not advance
  `st_blocks`) and path-dependent (standard vs shared_blocks).
- **The log already supports in-place rolling lines** for rsync progress2:
  `controller._append_log_line` (controller.py:419) treats any `\r`-bearing
  line as an in-place update, replacing the last line when that last line
  matches `_looks_like_progress` (controller.py:833) — which recognizes only
  the rsync `%`+`/s`/`:` pattern. Heartbeat lines (Chinese, no `%`) would
  NOT match, so without a change they would each append → log spam.
- **The manifest is small here** (6440 entries) so `_restore_metadata` is
  fast today, but for large manifests its single "restoring metadata…" line
  is itself a silent gap. The loop is the natural place for real `i/N`.
- **`e2fsck -fy` already prints** Pass 1–5, so it is not a silent gap.
- **The on-screen `ProgressBar`** (main.qml:472) is `indeterminate: true` —
  an honest "busy" indicator, not a fake percentage. It stays.

## Goals / Non-Goals

**Goals**
- During `mke2fs -d` / `e2fsdroid` fill, the log shows a rolling line
  reflecting **real bytes written** (from `st_blocks`), updated ~once per
  second — not a frozen "mke2fs -d …" line for minutes.
- The rolling line replaces itself in place (one line for the whole fill),
  reusing the same in-place mechanism rsync progress2 already uses — no log
  spam, no RichText history growth blowup.
- `_restore_metadata` shows real `i/N` progress for large manifests.
- No fake/authoritative percentage is presented; any percentage shown is
  explicitly an approximate proxy from `st_blocks`.

**Non-Goals**
- A precise fill percentage — not achievable with e2fsprogs; not pursued.
- Removing the `indeterminate` progress bar — it is honest and stays.
- Changing pack internals, image format, AVB, CLI, or the backend size cap.
- Progress for `cp -al` / deletion loop / `_du` / `img2simg` — they are
  short; the existing single stage line is sufficient.

## Decisions

### D1. Heartbeat = real `st_blocks` bytes, watcher in `root_helper`
**Choice**: In `_cmd_pack`, wrap the `_pack.pack(...)` call with a daemon
`threading.Thread` that every ~0.8 s does `os.stat(args.output).st_blocks`,
computes `written = st_blocks * 512`, and calls `_progress(...)` with a
`\r`-prefixed line. The thread exits when `pack.pack()` returns (a stop
`Event` set in the main thread after the call). While the output file does
not yet exist (pre-`mke2fs`) or was removed, the watcher emits nothing
rather than erroring.
**Rationale**: the helper is the process that runs as root and already
owns the `_progress` → stderr channel; the output image path (`args.output`)
is known there. Polling `st_blocks` is a cheap `stat`, ~1 Hz, negligible.
Doing it in the helper (not `pack.py`) keeps `pack.py` CLI-usable and
unchanged, and avoids threading inside the library.
**Alternatives**: poll from the GUI side (rejected — the GUI is a normal
user and the output image is root-owned mid-pack; `stat` may still work for
`st_blocks` but the file is being written by the root helper and the GUI
would need to know the output path + target size — more coupling); drive
the heartbeat from inside `pack.py` (rejected — adds a thread to the
library, affects CLI callers, and `pack.py` would need to know it's being
watched); parse `mke2fs` stderr for progress (rejected — there is none
during fill).

### D2. The CLI does not get the heartbeat (by default)
**Choice**: The watcher lives in `root_helper._cmd_pack`, which is only
invoked by the GUI via `pkexec`. The CLI (`cli.py`) calls `pack.pack()`
directly, so it is unaffected and remains as-is. If CLI progress is later
wanted, `pack.py`'s existing `on_line` already lets the CLI print stages;
the heartbeat is a GUI-specific layering concern.
**Rationale**: keeps the change scoped to the GUI log problem the user
reported; the CLI already streams `on_line` stages to stdout and is not
"silent" in the same way the GUI dock is.
**Alternatives**: move the watcher into `pack.py` so both paths benefit
(rejected per D1 — library threading + CLI behavior change, out of scope).

### D3. Target bytes for the approximate percentage
**Choice**: The watcher computes `target_bytes = build_block_count *
block_size`, where `build_block_count = target_blocks or
original_block_count` and `block_size = man.block_size or 4096`, loading
the manifest the same way `pack._load_manifest` does (the helper has the
workspace path). It then emits e.g.
`"⟳ 正在构建镜像… 已写入 2.34 GB  (约 41%)"`. The "约" (approx) makes the
non-authoritative nature explicit. If the manifest can't be loaded, the
watcher omits the percentage and reports only "已写入 N GB" (still a real
signal).
**Rationale**: the percentage, though approximate, is what makes the log
feel like progress rather than a frozen counter; deriving it from the same
`build_block_count`/`block_size` `pack.py` uses keeps it consistent. The
"约" framing protects against the non-linearity/sparsity stalls.

**Empirical validation (real `system.img`, shared_blocks path,
`e2fsdroid -s`, 11.58 GB staging → 11.41 GB apparent image, 325 s fill)**:
`st_blocks` grew **monotonically from 0 → 10.705 GB**, ending at **93.8% of
apparent** — which exactly equals the true fill ratio
(`2613480 / 2786222` blocks, reported by e2fsdroid itself). So against
`target_bytes = build_block_count * block_size`, the percentage is a sound
proxy that ends at the real fill ratio (≤ 100%), not a synthetic number.
An earlier observation of "only 2.55 GB allocated" was a **mid-fill
snapshot** (it matches the curve at t≈34 s), not the final state — it grew
to 10.7 GB as fill continued, which itself confirms the proxy tracks
progress. `e2fsck -fy` (run after fill) does **not** change `st_blocks`
(10.705 → 10.705 GB), so the percentage is stable across the validate step.

Two caveats the design must absorb (both already framed by "约"):
- **Non-linear with periodic stalls**: the delta drops to ~0 for several
  consecutive seconds at multiple points (e.g. t≈117–124, 143–152, 179–183,
  234–241, 261–272) — e2fsdroid is doing non-writing work (dedup hashing,
  inode/directory creation). The percentage will visibly pause even though
  work continues; it must not be mistaken for a hang.
- **Final plateau**: after all blocks are written, `st_blocks` sits at the
  fill ratio (~94%) for ~5–10 s while e2fsdroid finishes dedup/cleanup, then
  the process exits. The heartbeat will show "约 94%" then jump to the next
  stage line. This is honest but could read as "stuck near done"; the
  heartbeat MAY switch to a "收尾中…" suffix once `st_blocks` has not
  advanced for N consecutive ticks while near the top, but it MUST NOT
  fabricate 100% (it shows the real ratio).

**Alternatives**: report bytes only, no percentage (kept as the fallback
when the manifest is unavailable; percentage is additive, not essential);
report a fake time-based percentage (rejected — that's exactly the fake
progress the user wants to avoid); normalize the percentage against a
predicted final fill ratio so it reaches 100% (rejected — the prediction is
itself an estimate and would re-introduce a synthetic number; the real
ratio ending at ~94% then "完成" is more honest).

### D4. In-place rolling render via a heartbeat sentinel
**Choice**: Heartbeat lines are emitted as `"\r⟳ 正在构建镜像… …"` (a
leading `\r` plus a `⟳` sentinel prefix). In `controller._append_log_line`,
broaden the in-place rule: when an incoming line carries `\r`, after
stripping to the post-`\r` segment, replace the last log line in place if
that last line is **either** rsync-progress (existing
`_looks_like_progress`) **or** a heartbeat (starts with the `⟳` sentinel).
Also, an incoming heartbeat replaces a prior heartbeat regardless. This
guarantees one rolling line for the whole fill, no spam.
**Rationale**: the existing `\r`-in-place mechanism was built exactly for
this (rsync progress2 rewrites one status line); reusing it keeps the
RichText log bounded (the core concern in controller.py:195–204). A
dedicated sentinel avoids mis-detecting real log lines and keeps
`_looks_like_progress` conservative and unchanged for rsync.
**Alternatives**: make `_looks_like_progress` also match Chinese heartbeat
text (rejected — brittle, risks collapsing real Chinese log lines); emit
heartbeats without `\r` and let them append (rejected — ~1 line/sec over a
multi-minute fill = hundreds of lines, exactly the spam the throttle was
built to prevent); drop the `\r` and instead have QML collapse consecutive
lines (rejected — moves logic to QML, harder than reusing the existing
rule).

### D5. Metadata restore: real `i/N`, throttled
**Choice**: In `_restore_metadata` (pack.py:329), every ~1000 processed
entries call `on_line` with a `\r`-prefixed
`"⟳ 元数据回写 i/N"` line. Use the same `⟳` sentinel so it rolls in place
under the D4 rule. On completion, the existing "restoring metadata…" stage
line already covers the finish; the heartbeat just fills the loop.
**Rationale**: for large manifests this loop is the silent gap; `i/N` is a
true ratio (entries processed / total entries), so unlike the fill
percentage this one is exact. ~1000-entry granularity bounds log noise
(the 6440-entry manifest here → ~6 updates).
**Alternatives**: emit per-entry (rejected — thousands of lines);
`e2fsdroid` path already applies metadata during population, so this
applies only to the standard mount-based restore path (correct — the
shared_blocks path sets `metadata_restored = True` without this loop).

### D6. Watcher robustness
**Choice**: The watcher thread: (1) swallows `OSError`/`FileNotFoundError`
from `stat` and simply skips that tick (file not created yet, or removed
between mke2fs and a retry); (2) stops on a `threading.Event` set right
after `pack.pack()` returns, and also stops if `_CANCEL.cancelled` becomes
true; (3) is a daemon thread so a crash never strands the helper. It must
not outlive the pack call.
**Rationale**: the output file is created, grown, and (on a retry path)
removed by `pack.py` itself; the watcher must never crash the pack over a
`stat` race. Daemon + stop-Event is the standard safe pattern.
**Alternatives**: rely on daemon-only (rejected — a slow tick could fire
after `_emit_result`, interleaving a heartbeat into the next operation's
log; the stop-Event prevents that).

## Open Questions

- **Tunable cadence.** ~0.8 s is a first guess balancing "feels alive"
  vs. log/`st_blocks` cost. The 325 s real fill above was sampled at 1 s
  with smooth visible movement; 0.8 s is a reasonable starting point. The
  value is a named constant, easy to tune during implementation.
- **Final-plateau suffix.** Whether to append "收尾中…" (or similar) once
  `st_blocks` has stalled for N ticks near the top, to avoid the "约 94%
  then jump to 完成" reading as a hang. Low-risk polish; decide during
  implementation against the real curve. Must not fabricate 100%.
- **Whether to also show elapsed time** in the heartbeat (e.g.
  "已写入 2.34 GB (约 41%, 38s)"). Real and useful; the watcher thread can
  track its own start. Decided to keep the first version to bytes +
  approximate %, add elapsed if it reads well. Polish, not structural.
- **Standard (`mke2fs -d`) path** was not exercised on a large tree here
  (this image is shared_blocks; the standard path would overflow this
  partition since staging 11.58 GB > 11.41 GB apparent). The 116 MB probe
  confirmed `st_blocks` grows to full allocation on the standard path;
  the curve shape on a large non-shared tree should be confirmed during
  implementation, but the mechanism is the same (write-back population).
