## Why

The generated `flash.sh` (`systemimgkit/pack.py`, `_FLASH_SCRIPT_TEMPLATE`) opens with:

```bash
# 1. Reboot into fastboot mode
echo "Rebooting to fastboot…"
adb reboot fastboot
```

This step is wrong on the merits for the dominant use case. `adb reboot fastboot` requires the device to be **booted into the OS with adb enabled**. But the typical reason a user rebuilds and flashes a `system.img` with this tool is that the current system image is broken — i.e. the device does **not** boot cleanly, so `adb` is not reachable. In that situation the reboot line is a no-op at best and a confusing failure at worst; the user must enter fastboot manually via hardware keys (power + volume-down) regardless.

Removing the step also aligns the script's stated prerequisites with reality: once `adb reboot fastboot` is gone, the script no longer invokes `adb` at all — only `fastboot`. Today the header still says *"Prerequisites: … adb/fastboot installed"*, which becomes misleading after the removal.

## What Changes

- **Remove the reboot-to-fastboot block** from `_FLASH_SCRIPT_TEMPLATE`: the `# 1. Reboot into fastboot mode` comment, the `echo "Rebooting to fastboot…"`, and the `adb reboot fastboot` line.
- **Fix the header prerequisites** to drop `adb` and state the device is expected to already be in fastboot mode.
- **Renumber** the remaining step comments (`# 2 … # 5` → `# 1 … # 4`) so the sequence reads cleanly. The `fastboot getvar product … || sleep 5` "wait for fastboot device" block becomes the new step 1 — it remains, since it usefully confirms the device is actually in fastboot before flashing.
- **No CLI/GUI surface change.** The removal is a template-text edit; `pack()`'s signature, `PackResult`, the CLI flags, and the GUI flow are untouched. No new flags or checkboxes.

### Capabilities

### Modified Capabilities
- `gui`: the generated `flash.sh` no longer performs `adb reboot fastboot`; it assumes the device is already in fastboot mode. The remaining sequence (`fastboot erase system`, `fastboot flash system`, `--disable-verification flash vbmeta`, commented resize hints, `fastboot -w`, `fastboot reboot`) is unchanged.

## Impact

- **Code**: `systemimgkit/pack.py` — edit the single `_FLASH_SCRIPT_TEMPLATE` constant (lines ~412–470). Nothing else.
- **Spec**: MODIFIES the `gui` capability's "Updated flash.sh script" requirement (currently defined in the un-archived `gui-qml-migration` change at `specs/gui/spec.md:104`). See `design.md` for the ordering dependency.
- **Tests**: `tests/test_pack_integration.py:84` asserts only that `flash.sh` *exists*, never its content, so it stays green. An optional new assertion (script does not contain `adb reboot fastboot`) is listed in tasks.
- **Risks**: a user who *did* rely on the script to auto-reboot a healthy, adb-connected device into fastboot now has to do that step themselves. This is intentional and documented in the header. No flashable artifact changes — `system_new.img` and the sparse/vbmeta handling are byte-identical.
- **No breaking changes** to the image output or the pack API.
