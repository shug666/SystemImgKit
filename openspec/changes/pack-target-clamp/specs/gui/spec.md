## MODIFIED Requirements

### Requirement: Pre-pack fit guard against the target partition
When the user initiates packing and a target partition size is set (`targetBlocks > 0`, from either probe or manual entry), the app SHALL estimate the remaining content size (original image content size minus the selected deletion reclaim) and SHALL refuse to start packing if that estimate exceeds the target partition capacity (`targetBlocks * block_size`), surfacing a clear error telling the user to delete more. When the target partition is larger than the original image (`targetBytes > original_image_size`), the app SHALL instead emit an informational message ("设备分区大于原镜像，将按原镜像大小建镜像，分区剩余空间不使用") and proceed to pack, consistent with the backend's clamp behavior — this is not a fit failure. When no target partition size is set (`targetBlocks == 0` — device not probed or no target entered), the app SHALL allow packing unconditionally without a fit check. The backend's precise size cap is retained as the authoritative backstop.

#### Scenario: Target set and content would not fit
- **WHEN** the user clicks "打包" with `targetBlocks > 0`, `targetBytes ≤ original_image_size`, and the estimated remaining content exceeds `targetBlocks * block_size`
- **THEN** the app shows an error ("删得不够：剩余内容超出目标分区") and does not start packing

#### Scenario: Target partition larger than the original image
- **WHEN** the user clicks "打包" with `targetBlocks > 0` and `targetBytes > original_image_size` (e.g. a probed partition bigger than the unpacked source image)
- **THEN** the app logs an informational message ("设备分区大于原镜像，将按原镜像大小建镜像，分区剩余空间不使用") and proceeds to pack; it does NOT show the "删得不够" error

#### Scenario: Target set and content fits
- **WHEN** the user clicks "打包" with `targetBlocks > 0`, `targetBytes ≤ original_image_size`, and the estimated remaining content is within the target capacity
- **THEN** packing proceeds normally

#### Scenario: No target set
- **WHEN** the user clicks "打包" with `targetBlocks == 0` (device not probed / no target entered)
- **THEN** no fit check is performed and packing proceeds unconditionally

#### Scenario: Cheap estimate passes but precise backend cap fails
- **WHEN** the cheap pre-pack estimate is within the target but the precise backend tree-walk cap rejects the image mid-pack
- **THEN** the backend error is surfaced to the user as a normal pack failure (the pre-pack check is a coarse early gate, not authoritative)
