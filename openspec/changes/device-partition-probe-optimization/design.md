## Context

This change refines three GUI flows in `systemimgkit/gui/controller.py` + `systemimgkit/gui/qml/main.qml`:

- `Controller.probeDevicePartition()` (controller.py:392) — currently calls `fastboot getvar partition-size:system_a` via `subprocess.run(..., timeout=30)` **on the Qt main thread**. No device → up to 30 s UI freeze; no device preflight.
- `Controller.targetBlocks` Property (controller.py:226) — settable from QML but **not** pushed back to QML. The QML `targetSizeField` (`main.qml:235`) only has `onTextChanged → Controller.targetBlocks = ...`; nothing reads the controller back, so a successful probe's value never appears. The field converts `gb * 1e9 / 4096` (decimal GB); the probe uses real bytes — inconsistent units for the same partition.
- `Controller.packTo()` (controller.py:435) — sets `tb = self._target_blocks or None` and packs immediately. No fit check before pack. The backend `pack.pack()` size cap (`pack.py:114`, `staging_size > target_bytes → SizeCapExceededError`) runs **mid-pack** after cp -al + deletions, not at click time.

Existing building blocks reused unchanged:
- `Worker`/`WorkerSignals` (`gui/workers.py`) — runs a callable `(on_line, cancel)` on a `QThread`, emits `finished`/`failed`/`cancelled` on the main thread. Already used by unpack/catalog/pack via `_start_worker`.
- `_start_worker(fn, on_done)` (controller.py:516) — sets busy, wires signals, routes the result to `on_done`.
- `AppCardModel.reclaim_total()` (models.py:251) and `BigFileModel.selected_size()` (models.py:522) — the selected deletion size, already summed in `_reclaim()`.
- `Manifest.original_image_size` / `block_size` / `block_count` (manifest.py:42) — source content/geometry; loaded via `Workspace` + `_load_manifest`. (The controller already has `self._cat`; the manifest is the pack-side source of original content size.)
- `Controller.infoMessage`/`errorMessage`/`append_warning` — existing modal/log channels for surfacing results.

## Goals / Non-Goals

**Goals**
- Probe never blocks the UI; no device → fast, clear error; no freeze.
- A successful probe visibly populates the "目标分区大小" field, in a consistent unit with manual entry.
- Clicking "打包" with a target partition set blocks early (before pack starts) when the remaining content is estimated to exceed the target; with no target set, pack proceeds unconditionally.
- No backend behavior change — `pack.py`'s precise `_du` cap stays as the authoritative backstop.

**Non-Goals**
- Not changing pack internals, image format, AVB, or CLI.
- Not auto-retrying probe or scanning multiple partitions (system_a only, as today).
- Not precisely computing remaining content (cheap estimate only; precise check stays in the backend).
- Not disabling the "打包" button proactively based on the fit estimate (decision D5: reject at click time, not by disabling — because the "no target → pass" rule means the button must remain usable regardless of `target_blocks`).

## Decisions

### D1. Probe runs as a Worker with a fastboot devices preflight
**Choice**: Rewrite `probeDevicePartition` to run via `_start_worker`. The worker first runs `fastboot devices` (short timeout); if output is empty, return `{"ok": False, "error": "未检测到处于 fastboot 模式的设备"}` without ever issuing `getvar`. If a device is present, run `fastboot getvar partition-size:system_a` and parse the `0x…` hex size as today. The result is applied in `_on_probed` on the main thread.
**Rationale**: every other long operation in the app already uses `_start_worker`; this removes the only main-thread subprocess and fixes both the freeze and the no-device case with one mechanism. The `fastboot devices` preflight is a fast, deterministic "is anything there" check.
**Alternatives**: preflight-only while keeping the rest on the main thread (rejected — still runs subprocess on the UI thread; partial fix); `fastboot getvar product` as the preflight (rejected — `fastboot devices` is the canonical presence check and is faster to fail with no device).

### D2. Reflect the probed size back to QML in real bytes
**Choice**: Add a new read-only `Property(int)` `targetBlocksBytes`-equivalent surface, but because `targetBlocks` already exists as the canonical value, instead emit a dedicated signal `targetSizeChanged` and add a **read-only display property** `targetSizeGB` (formatted string) whose change signal fires whenever `self._target_blocks` changes (including from a probe and from `set`). QML binds the `targetSizeField.text` to this property, replacing the free `onTextChanged` write path. To avoid a feedback loop (binding writes → sets targetBlocks → signal → re-bind), the QML binding is one-directional for display while user edits are captured by `onTextChanged` guarded by a `__updating` flag so the controller-originated update does not re-write through.
**Rationale**: keeps `target_blocks` as the single source of truth (in blocks), removes the decimal-GB vs real-bytes mismatch (the property is computed from `target_blocks * block_size`, block_size from the manifest or 4096), and gives QML a real binding. The flag-guarded write keeps manual entry working.
**Alternatives**: make `targetBlocks` a QML `Property` with a `notify` and let QML bind both ways (rejected — Qt two-way bindings to a TextField are error-prone with parse/format); store the probed GB string directly (rejected — reintroduces the unit mismatch and loses the canonical block value).

### D3. Units are real bytes end to end
**Choice**: probe computes `size_bytes` then `blocks = size_bytes // block_size` (block_size from the loaded manifest when available, else 4096) — not `// 4096` hardcoded. The QML field displays GB derived from `target_blocks * block_size / 1e9`; manual entry parses GB → `Math.round(gb * 1e9 / block_size)`. Both sides now reference the same `block_size`.
**Rationale**: the partition is an exact byte count; using real bytes and the manifest's block_size makes probe, manual entry, and pack agree. The decimal-GB (`1e9`) display convention is preserved for the field (matches the existing hint text "如 7.68"), but it is consistently applied in both directions.
**Alternatives**: switch to GiB/1024³ (rejected — changes user-facing hint text and the documented "GB" unit; out of scope for this fix).

### D4. Pre-pack fit guard: cheap estimate, trigger on target_blocks > 0
**Choice**: In `packTo`, after computing the deletion set and before `_start_worker(pack…)`, if `self._target_blocks > 0`: compute `target_bytes = self._target_blocks * block_size` and `estimate_remaining = original_content_size - reclaim`, where `reclaim = app_model.reclaim_total() + bigfile_model.selected_size()` and `original_content_size` is `manifest.original_image_size` (loaded from the workspace manifest). If `estimate_remaining > target_bytes`, emit `errorMessage` "删得不够：剩余内容约 X 字节 > 目标分区 Y 字节" and `return` without starting pack. If `target_blocks == 0`, skip the check entirely and pack.
**Rationale**: `target_blocks > 0` is the exact "a target partition limit is set" predicate, regardless of whether it came from a probe or manual entry (decision confirmed: treat both identically). `original_image_size − reclaim` is a cheap upper-bound estimate available without a tree walk; it can be optimistic (fs overhead, shared-blocks dedup), so the backend's precise `_du` cap in `pack.py` remains the authoritative backstop and will catch the near-boundary cases the cheap estimate misses. `original_image_size` is the source image's pre-footer size already stored in the manifest.
**Alternatives**: precise `_du(workspace.tree) − reclaim` at click time (rejected per decision — a full tree walk of thousands of root-owned files on the click path, needs its own worker; the cheap estimate catches the common "deleted far too little" case and the backend catches the rest); trigger only when a `probed` flag is set (rejected — diverges manual-entry vs probe behavior for no benefit).

### D5. Reject at click time, not by disabling the button
**Choice**: The "打包" button stays enabled per the existing `canPack` binding (`_cat is not None and not _busy`). The fit check happens inside `packDefault`/`packTo`; on failure it shows `errorMessage` and returns. The button is never disabled based on the fit estimate.
**Rationale**: the "no target → unconditional pass" rule means the button must be usable when `target_blocks == 0`; a fit-based disabled state would contradict that and hide the reason. Rejecting at click time with an explicit message is clearer than a greyed-out button with no explanation.
**Alternatives**: disable the button when the estimate exceeds the target (rejected — hides the cause and conflicts with the pass-through rule).

## Risks / Trade-offs

- **[Cheap estimate is optimistic]** → a selection just under the bound may pass the pre-pack check yet fail the backend's precise `_du` cap. Mitigation: acceptable; the backend error is already surfaced clearly. Documented in the proposal.
- **[Block size assumed from manifest]** → if the manifest isn't loaded yet (pre-unpack), the probe/field use 4096 as the fallback. Mitigation: probing/packing both require a workspace+manifest in practice; the fallback matches the historical hardcoded 4096.
- **[QML binding feedback loop]** → display binding + `onTextChanged` write could oscillate. Mitigation: the `__updating` guard flag in QML suppresses the write during a controller-originated update (D2).
- **[fastboot devices also blocks on a misbehaving device]** → rare; bounded by a short timeout on the `fastboot devices` preflight. Mitigation: the preflight timeout is short (a few seconds), and the Worker means the UI is never frozen regardless.

## Open Questions

- Should the pre-pack error offer a "still pack anyway (I accept it may not flash)" override? (Leaning: no for v1 — the backend already enforces; an override would just defer to the same mid-pack failure. Keep the message actionable: tell the user to delete more.)
