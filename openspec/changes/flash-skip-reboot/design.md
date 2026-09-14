## Context

`flash.sh` is produced verbatim from a single string constant, `_FLASH_SCRIPT_TEMPLATE`, in `systemimgkit/pack.py`. `_write_flash_script` (pack.py:517) does `__SYS__/__SPARSE__/__VBMETA__` placeholder substitution only — there is no per-device or per-run variation of the reboot step. So the change is a pure template-text edit; no new parameters need to thread through `pack()`, `PackResult`, the CLI, or the GUI.

## Decisions

### D1 — Always remove, not flag-gated
The reboot block is removed unconditionally rather than behind a `--reboot-to-fastboot` flag / GUI checkbox. Rationale: the step is actively wrong for the dominant (broken-system) case, and gating it would add API surface (`pack(reboot=…)`, CLI flag, GUI control) for a marginal convenience that the user can trivially do themselves with `adb reboot fastboot` in a terminal. Keep the template dumb and correct for the common path.

### D2 — Keep the "wait for fastboot device" block
After removing the reboot, the `fastboot getvar product 2>/dev/null || sleep 5` block stays and becomes the new step 1. It confirms the device is actually reachable in fastboot before the destructive `fastboot erase system`. This is the genuinely useful "are we ready to flash?" check and is independent of how the device *got* into fastboot.

### D3 — Fix the header prerequisite line
Current header: `# Prerequisites: bootloader UNLOCKED, device connected via USB, adb/fastboot installed.`
After removal the script invokes only `fastboot`, never `adb`. The header is updated to drop `adb` and state the device must already be in fastboot mode. The "Review before running" / "never re-signs" lines stay.

### D4 — Renumber step comments
Comments are renumbered 1–4 (erase+flash, vbmeta, resize-hints, wipe+reboot) so the reader isn't left with a missing "# 1" and a `# 2` that comes first.

## Spec ordering dependency

The requirement being modified — "Updated flash.sh script" — currently lives in the **un-archived** `gui-qml-migration` change (`openspec/changes/gui-qml-migration/specs/gui/spec.md:104`), not yet in the canonical `openspec/specs/gui/spec.md`. This change's spec delta MODIFIES that requirement.

Two resolution paths, either is fine:
- If `gui-qml-migration` is archived **first**, its requirement lands in `openspec/specs/gui/spec.md` with `adb reboot fastboot`, and this change then MODIFIES the canonical requirement to remove it.
- If this change is implemented **before** `gui-qml-migration` is archived, the two changes' `specs/gui/spec.md` deltas must be reconciled at archive time (the canonical requirement ends up *without* `adb reboot fastboot`).

Either way the end state is the same: the canonical `gui` "Updated flash.sh script" requirement lists the sequence **without** `adb reboot fastboot`.

## Open questions

None. (The always-remove vs. flag-gate choice is settled by D1 in favor of always-remove.)
