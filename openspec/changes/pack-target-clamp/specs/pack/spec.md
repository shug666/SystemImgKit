## ADDED Requirements

### Requirement: Target partition larger than the original image builds at the original size
When a target partition size is supplied (`target_blocks > 0`, from either a device probe or manual entry) and that target is greater than or equal to the original image's block count, `pack` SHALL build the output image at the original block count rather than raising an error. The tool remains shrink-only: the output image is never larger than the original image. A target partition larger than the original image means no shrinking is needed, which is equivalent to the no-target (`target_blocks == 0`) default. `pack` SHALL emit an informational line naming both the target and original block counts and stating that the image is built at the original size with the partition's remaining space left unused.

#### Scenario: Target larger than original (probed partition bigger than source image)
- **WHEN** `pack` is called with `target_blocks > original_block_count`
- **THEN** `pack` does not raise; it builds the image at `original_block_count`, emits an info line ("目标分区 N 块大于原镜像 M 块，按原镜像大小建镜像，分区剩余空间不使用"), and the result `block_count` equals `original_block_count`

#### Scenario: Target equal to original
- **WHEN** `pack` is called with `target_blocks == original_block_count`
- **THEN** `pack` builds the image at `original_block_count` (unchanged from prior behavior)

#### Scenario: Target smaller than original (shrink)
- **WHEN** `pack` is called with `0 < target_blocks < original_block_count`
- **THEN** `pack` builds the image at `target_blocks` (unchanged from prior behavior)

#### Scenario: No target set
- **WHEN** `pack` is called with `target_blocks == 0` (or None)
- **THEN** `pack` builds the image at `original_block_count` with no target-size info line (unchanged from prior behavior)

#### Scenario: Shrink-only contract preserved
- **WHEN** `pack` is called with any `target_blocks` value (0, smaller, equal, or larger than original)
- **THEN** the output image's block count never exceeds `original_block_count`
