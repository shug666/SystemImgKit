## 1. Heartbeat watcher in root_helper (fill-phase real bytes)

- [x] 1.1 In `root_helper._cmd_pack`, load the manifest (via `Workspace` + `manifest.Manifest.load`) to obtain `block_size` and `original_block_count`; compute `target_bytes = (target_blocks or original_block_count) * block_size`; tolerate manifest load failure (fall back to bytes-only, no percentage)
- [x] 1.2 Add a `_Heartbeat` helper (or inline thread) that, given `output_path`, `target_bytes`, a `stop: threading.Event`, and `cancel`, polls `os.stat(output_path).st_blocks` every ~0.8 s and emits `\r⟳ 正在构建镜像… 已写入 N GB  (约 NN%)` via `_progress` (bytes-only form when `target_bytes` is unknown); swallow `OSError`/`FileNotFoundError` and skip the tick
- [x] 1.3 Start the watcher daemon thread immediately before `_pack.pack(...)` and set `stop` right after it returns (also stop on `_CANCEL.cancelled`); ensure the thread is a daemon and is joined with a short timeout so it never outlives the call or interleaves into the next operation's log
- [x] 1.4 Make the cadence (`HEARTBEAT_INTERVAL_S`, ~0.8) and the sentinel (`⟳`) named constants shared with the controller side

## 2. In-place rolling render for heartbeat lines (controller)

- [x] 2.1 In `controller._append_log_line`, when an incoming line carries `\r`, after `rsplit("\r", 1)[-1]`, replace the last log line in place if the last line matches rsync progress (`_looks_like_progress`, unchanged) **or** starts with the `⟳` heartbeat sentinel
- [x] 2.2 Add a `_looks_like_heartbeat(line)` helper (last line starts with `⟳`) and combine it with `_looks_like_progress` in the replace predicate; keep both conservative — never collapse a real log line
- [x] 2.3 An incoming heartbeat also replaces a prior heartbeat (covered by 2.1/2.2), so the whole fill phase is one rolling line; verify the RichText log line count does not grow during a long fill

## 3. Real `i/N` progress for metadata restore (pack.py)

- [x] 3.1 In `pack._restore_metadata`, accept the total `len(man.entries)` and emit `\r⟳ 元数据回写 i/N` via `on_line` every ~1000 processed entries (same `⟳` sentinel → rolls in place under the task-2 rule)
- [x] 3.2 Throttle by count (every 1000) not by time, so it is deterministic and cheap for small manifests (6440 entries → ~6 updates); ensure the final stage line ("restoring metadata…" / the existing completion log) still prints after the loop
- [x] 3.3 Confirm the shared_blocks path (which sets `metadata_restored = True` without this loop) is unaffected

## 4. Tests & validation

- [x] 4.1 Unit test: the heartbeat watcher emits no line when the output file does not exist, emits increasing "已写入 N GB" values as `st_blocks` grows (use a temp file grown between ticks), and stops promptly when `stop` is set (no post-stop emission)
- [x] 4.2 Unit test: heartbeat computes the approximate percentage as `st_blocks*512 / target_bytes` when `target_bytes` is known, and omits the percentage (bytes-only) when the manifest is unavailable
- [x] 4.3 Unit test: `_looks_like_heartbeat` matches `⟳`-prefixed lines and not real log lines; the combined in-place rule replaces a prior `⟳` line with a new `⟳` line and leaves a real line intact when the incoming line is a normal log
- [x] 4.4 Unit test: `_restore_metadata` emits `⟳ 元数据回写 i/N` at the expected count granularity (e.g. for 2500 entries → updates at 1000, 2000, and final), and does not emit per-entry
- [ ] 4.5 Manual smoke test: pack a real ~2 GB system tree in the GUI — the log must show a single rolling "正在构建镜像… 已写入 N GB (约 NN%)" line during the silent `mke2fs -d` fill (no hundreds of appended lines), advance to "元数据回写 i/N", then "e2fsck" Pass lines, then "打包完成"; the `indeterminate` progress bar remains throughout. Confirm a shared_blocks image packs with the same heartbeat behavior.
- [x] 4.6 Empirical curve check (reference data already captured on the real A17 `system.img`, shared_blocks path, 11.58 GB staging, 325 s fill): `st_blocks` grows monotonically 0 → ~94% of apparent with periodic ~5–10 s stalls during dedup/inode phases and a final plateau at the fill ratio before exit; `e2fsck -fy` does not change `st_blocks`. Confirm the implemented heartbeat reproduces this shape (movement + honest stalls, no fabricated 100%), and that the percentage ends near the true fill ratio rather than at a fixed cap.
