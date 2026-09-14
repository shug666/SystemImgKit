## Why

When the user probes the device's `system_a` partition, the probed partition is frequently **larger** than the source image that was unpacked (OEMs ship a `system.img` slightly smaller than the configured partition, leaving headroom). In that case `pack.py:86` raises:

```
SystemImgKitError: 目标分区 2,518,561 块大于原分区 2,480,409 块,无法增大镜像(工具只用于缩小)。
```

This breaks the probe→pack flow at its most common outcome. The error is wrong on the merits: flashing a raw ext4 image into a **larger** partition is perfectly legal (the unused tail is simply free space; `e2fsck` accepts it). The tool's contract is "shrink-only" — and a target partition larger than the original image means **no shrinking is needed**, which is the tool's default path. The error conflates two different meanings of `target_blocks`:

| `target_blocks` meaning | target > original ⇒ correct action |
|---|---|
| "build the image this large" (manual entry wanting to enlarge) | refuse — tool cannot enlarge |
| "the device partition is this large" (probe result) | build at original size — already fits |

The code only handles the first meaning. The probe — the mainstream entry point introduced by `device-partition-probe-optimization` — falls into the second meaning and trips the guard.

A secondary mismatch: the GUI pre-pack fit guard (`controller.py:_prepack_fit_ok`) only tests `estimate_remaining > target_bytes`. When `target > original`, the estimate *passes* (remaining < target), so packing is allowed to start, only to fail mid-worker in `pack.py`. The failure surfaces as a generic "打包失败" rather than a clear, early message.

## What Changes

- **Backend clamps, not errors, when target ≥ original.** In `pack.pack()`, when `target_blocks` is set and `target_blocks >= original_block_count`, the build size SHALL be `original_block_count` (i.e. "no shrinking needed") with an informational line, instead of raising for the `>` case. The tool stays shrink-only — it never builds an image larger than the original. The `target_blocks == 0` path (build at original size, no target) is unchanged.
- **GUI pre-pack guard reports the clamp case clearly.** When `target_blocks > original_block_count` (in block terms, `target_bytes > original_content_size`), the pre-pack guard SHALL log an informational message ("设备分区大于原镜像，将按原镜像大小建镜像，分区剩余空间不使用") and proceed, rather than silently passing a value that the backend then clamps. This keeps the cheap estimate and the backend clamp in agreement and tells the user upfront.

### Capabilities

### Modified Capabilities
- `pack`: target partition larger than the original image no longer errors; it builds at the original block count (the shrink-only contract is preserved — nothing is enlarged). Equal-to and larger-than both build at the original size.
- `gui`: the pre-pack fit guard recognizes the "target larger than original" case and reports it as an informational proceed, consistent with the backend clamp.

## Impact

- **Code**: `systemimgkit/pack.py` (replace the `target_blocks > original_block_count` raise with a clamp + `on_line` info; the `==` case already builds at original and just becomes explicit), `systemimgkit/gui/controller.py` (`_prepack_fit_ok` adds the `target_bytes > original_content_size` informational branch). CLI (`cli.py`) is affected only insofar as it stops erroring on the same input — its flags are unchanged.
- **Risks**: a user who manually enters a larger `target_blocks` *intending* to enlarge the image no longer gets a hard error; they get a clamp + info line and an original-sized image. This is strictly better (the old error produced nothing usable; the new behavior produces a correct, flashable image) but changes a surfaced error into a silent-ish clamp. Mitigated by the explicit `on_line` message naming both block counts.
- **No breaking changes**: images produced for the `target == 0` and `target < original` paths are byte-identical to today. The only behavioral change is the former-error case becoming a valid original-sized build. AVB Strategy A (footerless raw ext4) is untouched.
