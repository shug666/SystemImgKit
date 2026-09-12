## MODIFIED Requirements

### Requirement: Non-blocking long operations with progress
All long operations (unpack, pack, validation, **device partition probe**) SHALL run in background `QThread` workers. The UI SHALL remain responsive and SHALL show a progress indicator driven by worker subprocess output. The UI SHALL allow the user to cancel an in-progress operation. No operation that issues an external subprocess (including `fastboot`) SHALL run on the Qt main thread.

#### Scenario: Progress during unpack
- **WHEN** unpack is running
- **THEN** the UI shows a progress bar advanced by parsing the worker's stderr, and the main window stays interactive

#### Scenario: Cancel a running operation
- **WHEN** the user clicks Cancel during a long operation
- **THEN** the worker terminates its subprocess, cleans up partial workspace files, and returns the UI to the idle state

#### Scenario: Probe with no device connected
- **WHEN** the user clicks "探测设备分区" and no device is connected in fastboot mode
- **THEN** the UI does not freeze, a `fastboot devices` preflight detects the absence, and the app shows a clear error ("未检测到处于 fastboot 模式的设备") without issuing a blocking `getvar`

#### Scenario: Probe runs in the background
- **WHEN** the user clicks "探测设备分区" and a device is connected
- **THEN** the probe runs in a background worker, the probe button reflects a busy state, and the main window stays interactive for the duration of the `fastboot` call

## ADDED Requirements

### Requirement: Probe reflects target size into the UI
A successful device partition probe SHALL set the target partition size (in blocks, derived from the probed byte size and the manifest block size) and SHALL reflect that value back into the "目标分区大小" UI field so the user can see the probe succeeded and what value was applied. The probe and manual field entry SHALL use a consistent unit (real bytes, with GB formatting applied at display).

#### Scenario: Successful probe populates the field
- **WHEN** the probe returns a `system_a` partition size
- **THEN** the "目标分区大小" field displays the size in GB derived from that value, and the underlying `targetBlocks` is set to the corresponding block count

#### Scenario: Manual entry and probe agree on units
- **WHEN** the user manually enters a GB value and separately probes the same partition
- **THEN** both paths produce the same `targetBlocks` for the same physical partition (no decimal-GB vs real-bytes mismatch)

### Requirement: Pre-pack fit guard against the target partition
When the user initiates packing and a target partition size is set (`targetBlocks > 0`, from either probe or manual entry), the app SHALL estimate the remaining content size (original image content size minus the selected deletion reclaim) and SHALL refuse to start packing if that estimate exceeds the target partition capacity (`targetBlocks * block_size`), surfacing a clear error telling the user to delete more. When no target partition size is set (`targetBlocks == 0` — device not probed or no target entered), the app SHALL allow packing unconditionally without a fit check. The backend's precise size cap is retained as the authoritative backstop.

#### Scenario: Target set and content would not fit
- **WHEN** the user clicks "打包" with `targetBlocks > 0` and the estimated remaining content exceeds `targetBlocks * block_size`
- **THEN** the app shows an error ("删得不够：剩余内容超出目标分区") and does not start packing

#### Scenario: Target set and content fits
- **WHEN** the user clicks "打包" with `targetBlocks > 0` and the estimated remaining content is within the target capacity
- **THEN** packing proceeds normally

#### Scenario: No target set
- **WHEN** the user clicks "打包" with `targetBlocks == 0` (device not probed / no target entered)
- **THEN** no fit check is performed and packing proceeds unconditionally

#### Scenario: Cheap estimate passes but precise backend cap fails
- **WHEN** the cheap pre-pack estimate is within the target but the precise backend tree-walk cap rejects the image mid-pack
- **THEN** the backend error is surfaced to the user as a normal pack failure (the pre-pack check is a coarse early gate, not authoritative)
