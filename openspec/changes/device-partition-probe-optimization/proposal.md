## Why

The GUI's "探测设备分区" (probe device partition) feature is unusable and partially broken in three ways, each of which either freezes the UI or silently lets the user build an image that cannot flash:

1. **Freeze with no device connected.** Clicking "探测设备分区" runs `fastboot getvar partition-size:system_a` via `subprocess.run(..., timeout=30)` **directly on the Qt main thread** (`controller.py:probeDevicePartition`). With no device attached, `fastboot` blocks waiting for a device, freezing the whole UI for up to 30 s. There is no preflight check for whether a device is even connected.
2. **Probed size never reaches the "目标分区大小" field.** `targetBlocks` is a one-way property: QML→Python works (the field's `onTextChanged` writes `Controller.targetBlocks`), but Python→QML does not — after a successful probe sets `self._target_blocks`, the `targetSizeField` text field is not bound to anything, so it stays showing the user's last typed value (default `"0"`). The user cannot see that the probe succeeded or what value was applied. Worse, the field uses `gb * 1e9 / 4096` (decimal GB) while the probe uses real bytes, so the two paths disagree for the same partition.
3. **No pre-pack fit check.** The pack backend already has a size cap (`pack.py:114` — `staging_size > target_bytes` raises `SizeCapExceededError`), but it runs **mid-pack**, after the tree is already hardlink-copied and deletions applied. Nothing checks at the moment the user clicks "打包". Per requirement, when a target partition size is set (`target_blocks > 0`, from either probe or manual entry) the app must estimate the remaining content size and **block packing** if it would not fit the target partition; if no target is set (device not probed / not detected, i.e. `target_blocks == 0`) it must **allow** packing unconditionally.

## What Changes

- **Probe moves off the main thread.** `probeDevicePartition` becomes a background `Worker` job (like unpack/catalog/pack), running a `fastboot devices` preflight before `fastboot getvar partition-size:system_a`. The UI stays responsive; the button shows busy/disabled while probing. No device → a clear error, no freeze.
- **Probed value reflects back into the UI.** Add a Python→QML read-only property exposing the current target size (in bytes, consistent unit), with a change signal. QML binds the "目标分区大小" field to it, so a successful probe populates the field. The field and probe now use the same unit (real bytes); display is formatted on read.
- **Pre-pack fit guard in the GUI.** Before starting pack, when `target_blocks > 0`, the controller estimates the remaining content size (original image content size − selected deletion reclaim) and compares to `target_blocks * block_size`. If it would not fit, it refuses to pack with a clear error ("删得不够，剩余内容超出目标分区") rather than letting pack run and fail mid-way. When `target_blocks == 0`, no check is performed and pack proceeds. The backend's precise `_du` cap remains as the authoritative backstop.

### Capabilities

### Modified Capabilities
- `gui`: probe runs non-blocking with device preflight; probed target size is reflected in the UI; a pre-pack fit guard blocks packing when the estimated remaining content exceeds the target partition and no target is set means unconditional pass-through.

## Impact

- **Code**: `systemimgkit/gui/controller.py` (probe slot → worker; new target-size property; pre-pack guard in `packTo`), `systemimgkit/gui/qml/main.qml` (bind target-size field to the new property; probe button busy state). No backend (`pack.py`) behavior change — its size cap is retained as the backstop.
- **Risks**: the pre-pack estimate is a cheap upper bound (original content − reclaim), not a precise tree walk; it can be optimistic (fs overhead, shared-blocks dedup) — hence the backend retains the precise check. A near-boundary selection may pass the cheap check and still fail the precise one; this is acceptable and surfaced as a normal pack error.
- **No breaking changes**: pure GUI-flow refinement; CLI is unaffected.
