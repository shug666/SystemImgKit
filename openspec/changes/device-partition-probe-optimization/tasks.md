## 1. Probe: move off the main thread with device preflight

- [x] 1.1 Extract the probe logic into a worker callable `_probe_job(on_line, cancel)` that runs `fastboot devices` (short timeout, ~5 s) and returns `{"ok": False, "error": "未检测到处于 fastboot 模式的设备"}` if the output is empty
- [x] 1.2 When a device is present, run `fastboot getvar partition-size:system_a`, parse the `0x…` hex size, and return `{"ok": True, "size_bytes": …, "blocks": size_bytes // block_size}` (block_size from the loaded manifest when available, else 4096)
- [x] 1.3 Rewrite `Controller.probeDevicePartition()` to call `self._start_worker(_probe_job, on_done=self._on_probed)` instead of running `subprocess.run` on the main thread
- [x] 1.4 Add `_on_probed(res)` to apply a successful result (`self._target_blocks = res["blocks"]`, emit signals, append warning, `infoMessage`) and surface failures via `errorMessage`; handle the worker `failed` path (fastboot missing/timeout) gracefully
- [x] 1.5 Wire the probe button's `enabled` to a busy state so it is disabled while probing (reuse `progressBusy` or a probe-specific flag), and ensure cancel works on the probe worker

## 2. Reflect probed size into the UI (consistent units)

- [x] 2.1 Add a read-only display property (e.g. `targetSizeGB`, string) computed from `self._target_blocks * block_size / 1e9`, with a dedicated change signal that fires whenever `_target_blocks` changes (probe, manual set, reset)
- [x] 2.2 Make `targetBlocks` setter emit the new signal so all paths (probe, QML write, reset) keep the display in sync
- [x] 2.3 In `main.qml`, bind the `targetSizeField.text` to the new display property; add an `__updating` guard flag so controller-originated updates do not re-trigger the `onTextChanged` write-back
- [x] 2.4 Keep `onTextChanged` parsing manual GB entry → `Controller.targetBlocks = Math.round(gb * 1e9 / block_size)`; ensure manual entry still works alongside the binding (flag-guarded)
- [x] 2.5 Remove the hardcoded `// 4096` in both probe and the QML parser in favor of the manifest block_size (4096 fallback), eliminating the decimal-GB vs real-bytes mismatch

## 3. Pre-pack fit guard

- [x] 3.1 In `packTo`, after computing `deletions` and before `_start_worker(pack…)`, load the original content size from the workspace manifest (`original_image_size`) and `block_size`
- [x] 3.2 Compute `reclaim = self.app_model.reclaim_total() + self.bigfile_model.selected_size()` and `target_bytes = self._target_blocks * block_size`
- [x] 3.3 When `self._target_blocks > 0`: if `original_content_size - reclaim > target_bytes`, emit `errorMessage` ("删得不够：剩余内容约 {X} 字节 > 目标分区 {Y} 字节，请多删一些") and `return` without starting pack
- [x] 3.4 When `self._target_blocks == 0`: skip the check entirely and proceed to pack (unconditional pass-through)
- [x] 3.5 Ensure `packDefault`/`packTo` both go through the guard (single code path); keep the backend `pack.py` `_du` size cap unchanged as the authoritative backstop

## 4. Tests & validation

- [x] 4.1 Unit test: `_probe_job` with no device (mock `fastboot devices` empty output) returns the "未检测到设备" error without issuing `getvar`
- [x] 4.2 Unit test: `_probe_job` with a device (mock `fastboot devices` non-empty + `getvar` returning `partition-size:system_a:0x…`) returns the correct byte/block values
- [x] 4.3 Unit test: pre-pack guard — `target_blocks > 0` and `original - reclaim > target_bytes` blocks pack (no worker started); `target_blocks == 0` passes through; `target_blocks > 0` and fits proceeds
- [x] 4.4 Unit test: target-size display property updates when `_target_blocks` changes via probe and via manual set, and computes GB consistently from blocks*block_size/1e9
- [ ] 4.5 Manual smoke test: with no device, click "探测设备分区" — UI must not freeze and shows the no-device error; with a device in fastboot, the field populates with the probed GB; delete too little, click "打包" → blocked with the "删得不够" message; delete enough → packs; leave target at 0 → packs unconditionally
