## Context

`pack.pack()` (`systemimgkit/pack.py:55`) sizes the output image from `target_blocks`:

```python
build_block_count = target_blocks or original_block_count
if target_blocks and target_blocks < original_block_count:
    on_line("目标分区 … — 按目标大小建镜像")
elif target_blocks and target_blocks > original_block_count:
    raise SystemImgKitError("…无法增大镜像(工具只用于缩小)。")
# implicit: target_blocks == original_block_count → build at original (falls through)
target_bytes = build_block_count * block_size
```

`target_blocks` arrives from two sources:
- **Probe** (`controller.py:_on_probed`): the *device partition size* — by construction ≥ the source image for OEM-built `system.img`. Larger-than-original is the **common** probe outcome, not an edge case.
- **Manual QML entry** (`targetSizeField`): the user-typed "目标分区大小" — historically intended as a shrink target.

A single field carries both semantics; the `>` branch assumes the manual-enlarge meaning and errors, but the probe meaning (the mainstream path) lands there too.

The GUI pre-pack guard (`controller.py:_prepack_fit_ok`, decision D4 of `device-partition-probe-optimization`) only tests `estimate_remaining > target_bytes`. When `target > original`, `estimate_remaining = original_content_size - reclaim` is *below* `target_bytes`, so the guard passes, packing starts, and `pack.py` then raises mid-worker — surfaced as a generic "打包失败" via `_on_packed`.

Existing building blocks reused unchanged:
- `Manifest.block_size` / `block_count` / `original_image_size` (`manifest.py:42`) — source geometry.
- `controller._prepack_fit_ok` — already loads the manifest, computes `target_bytes` and `original_content_size`; the new branch reuses these.
- The `on_line` progress channel — already used for the `< original` informational line.

## Goals / Non-Goals

**Goals**
- A probed (or manually entered) target partition larger than the original image produces a valid, flashable image at the original block count, with a clear informational message — not an error.
- The tool remains shrink-only: the output is never larger than `original_block_count`.
- The GUI pre-pack guard and the backend clamp agree on the `target > original` case, so the user is told upfront and packing does not start-then-fail.

**Non-Goals**
- Not supporting image enlargement (resizing the ext4 filesystem up to `target_blocks`). Stay shrink-only; the `> original` case is treated as "no shrinking needed", not as a request to grow.
- Not changing AVB Strategy A, the manifest, the CLI flags, or the `target < original` / `target == 0` paths.
- Not computing a precise remaining-content estimate at click time (the cheap `original - reclaim` estimate is retained; the backend `_du` cap stays the authoritative backstop).

## Decisions

### D1. Clamp in the backend, not in the GUI
**Choice**: `pack.pack()` replaces the `target_blocks > original_block_count` raise with a clamp: `build_block_count = original_block_count`, plus an `on_line` info naming both counts and noting "按原镜像大小建镜像，分区剩余空间不使用". The `==` case is made explicit (same outcome). `target_blocks == 0` and `target_blocks < original_block_count` are unchanged.
**Rationale**: the backend is the authoritative entry point shared by CLI and GUI; fixing it there covers both. The clamp preserves the shrink-only contract (output ≤ original). Treating `>` as "no shrinking needed" is exactly the `== 0` default semantics, so the change collapses the `>` and `==` cases onto the already-correct default path.
**Alternatives**: error with a better message telling the user to clear the field (rejected — breaks the probe→pack flow on its most common outcome and pushes a workaround onto the user for a case that needs no workaround); clamp only in the GUI controller, leaving CLI erroring (rejected — diverges the two entry points; the CLI user hitting the same probe-style input still errors).

### D2. Informational (not warning) tone for the clamp
**Choice**: the clamp emits an `on_line` info line, not an `errorMessage`/warning. It is not a degraded outcome — the image is correct and flashable.
**Rationale**: a warning implies something is wrong; nothing is. Matches the existing `< original` info line's tone ("目标分区 … — 按目标大小建镜像").
**Alternatives**: append a `PackResult.warning` so it shows in the post-pack log (rejected as primary signal — the user should know *before/during* the build, not after; the `on_line` fires at the start). Could *also* append a `warning` for the record; left as an implementation detail, not required.

### D3. GUI guard adds the same case, as an informational proceed
**Choice**: in `_prepack_fit_ok`, after computing `target_bytes` and `original_content_size`, if `target_bytes > original_content_size` (target partition larger than original image, in consistent byte units), emit an `append_warning` info ("设备分区大于原镜像，将按原镜像大小建镜像，分区剩余空间不使用") and `return True` (proceed) — without the "预检通过/未通过" framing, since there is nothing to fit-check.
**Rationale**: keeps the guard and the backend clamp aligned: the guard no longer silently passes a value the backend will clamp; it states the clamp upfront. Using byte comparison (`target_bytes > original_content_size`) matches the guard's existing unit and avoids a second manifest block-count lookup. The `estimate_remaining > target_bytes` check is still performed for the `target ≤ original` cases that need it.
**Alternatives**: leave the guard as-is and let only the backend clamp (rejected — the user sees no early message; the backend `on_line` only appears mid-pack in the worker log, later and less prominent than the click-time guard message); have the guard *clear* `target_blocks` to 0 in this case (rejected — mutates user-visible state behind their back; the backend clamp is enough).

### D4. Unit consistency between guard and backend
**Choice**: the guard compares in bytes (`target_bytes = self._target_blocks * block_size` vs `original_content_size = man.original_image_size`); the backend compares in blocks (`target_blocks` vs `original_block_count = man.block_count or original_image_size // block_size`). Both derive from the same manifest fields, so they agree.
**Rationale**: the guard already works in bytes (D4 of the prior change); the backend already works in blocks. Forcing one unit across both would be a larger churn for no correctness gain — `blocks * block_size` and `original_image_size` are consistent by manifest invariant (block_count = original_image_size // block_size). No change needed beyond documenting the invariant reliance.

## Risks / Trade-offs

- **[Manual-enlarge intent loses its error]** → a user who types a larger `target_blocks` wanting to enlarge the image now gets a clamp + info instead of a hard error. Mitigation: the info line names both block counts ("目标分区 N 块大于原镜像 M 块，按原镜像大小建镜像"), making the clamp visible; the outcome (a correct, original-sized, flashable image) is strictly more useful than the prior error. Documented in the proposal.
- **[Silent clamp if `on_line` is not observed]** → CLI/programmatic callers that ignore `on_line` would not see the clamp message. Mitigation: the behavior (build at original size) is correct regardless; the message is advisory, not load-bearing.
- **[Guard/backend disagreement on near-equal values]** → byte vs block comparison could disagree by a sub-block rounding when `target_bytes` and `original_content_size` straddle a block boundary with `target_blocks` derived from a different block_size than the manifest. Mitigation: both use the manifest block_size (guard via `man.block_size`, backend via `man.block_size or 4096`); the invariant holds. The `>` is the operative comparison and is robust to ±1-block jitter since the clamp outcome is identical to the `==` outcome.

## Open Questions

- Should the clamp also append a `PackResult.warning` so it appears in the structured post-pack result (e.g. for CLI JSON consumers), in addition to the `on_line` info? (Leaning: yes, cheap and helps non-interactive consumers — but not required for correctness.)
