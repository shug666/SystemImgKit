## 1. Backend: clamp when target ≥ original

- [x] 1.1 In `pack.pack()`, replace the `elif target_blocks and target_blocks > original_block_count:` raise with a clamp branch: set `build_block_count = original_block_count` and emit an `on_line` info ("目标分区 {target_blocks:,} 块大于原镜像 {original_block_count:,} 块，按原镜像大小建镜像，分区剩余空间不使用")
- [x] 1.2 Make the `target_blocks == original_block_count` case explicit (same outcome — build at original; an `on_line` info is optional but keep behavior identical to today's fall-through)
- [x] 1.3 Leave the `target_blocks == 0` and `target_blocks < original_block_count` branches byte-identical to current behavior
- [x] 1.4 (Optional, per design D2/open question) append a `PackResult.warning` recording the clamp, so CLI/JSON consumers see it alongside the `on_line` info

## 2. GUI: pre-pack guard recognizes the clamp case

- [x] 2.1 In `controller._prepack_fit_ok`, after computing `target_bytes` and `original_content_size`, add a branch: if `target_bytes > original_content_size`, emit `append_warning` ("设备分区大于原镜像，将按原镜像大小建镜像，分区剩余空间不使用") and `return True` (proceed) — before the `estimate_remaining > target_bytes` check
- [x] 2.2 Keep the existing `estimate_remaining > target_bytes` block (the "删得不够" refusal) for the `target ≤ original` cases that need it; the new branch only short-circuits the `target > original` case
- [x] 2.3 Verify the `target_blocks == 0` unconditional pass-through (in `packTo`, not `_prepack_fit_ok`) is unchanged

## 3. Tests & validation

- [x] 3.1 Unit test (`tests/`): `pack` with `target_blocks > original_block_count` no longer raises; it builds at `original_block_count` and the result `block_count == original_block_count`; the `on_line` callback receives a line mentioning both block counts
- [x] 3.2 Unit test: `pack` with `target_blocks == original_block_count` builds at the original size (regression — same as today's fall-through)
- [x] 3.3 Unit test: `pack` with `target_blocks < original_block_count` builds at `target_blocks` (regression, unchanged)
- [x] 3.4 Unit test: `pack` with `target_blocks == 0` builds at `original_block_count` (regression, unchanged)
- [x] 3.5 Unit test: GUI `_prepack_fit_ok` with `target_bytes > original_content_size` returns `True` and appends the "设备分区大于原镜像" info, without emitting the "删得不够" error
- [ ] 3.6 Manual smoke test: probe a device whose `system_a` is larger than the unpacked image → the pre-pack log shows the "设备分区大于原镜像" info; packing completes; the output image's block count equals the original; `e2fsck` is clean; the image flashes
