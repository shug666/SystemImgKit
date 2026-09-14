## 1. Template edit

- [x] 1.1 In `systemimgkit/pack.py` `_FLASH_SCRIPT_TEMPLATE`, remove the three-line reboot block: the `# 1. Reboot into fastboot mode` comment, `echo "Rebooting to fastboot…"`, and `adb reboot fastboot`
- [x] 1.2 Update the header prerequisite line: drop `adb` from "adb/fastboot installed" and add that the device must already be in fastboot mode; keep the "Review before running / never re-signs" lines
- [x] 1.3 Renumber the remaining step comments so the "wait for fastboot device" block is `# 1` and the rest follow `# 2 … # 4` (erase+flash, vbmeta, resize-hints, wipe+reboot)
- [x] 1.4 Leave `_write_flash_script` placeholder substitution (`__SYS__/__SPARSE__/__VBMETA__`) untouched

## 2. Tests & validation

- [x] 2.1 Add an assertion in `tests/test_pack_integration.py` (or a new test) that the generated `flash.sh` does **not** contain `adb reboot fastboot` and does not contain `adb` as a command
- [x] 2.2 Add an assertion that the `flash.sh` header prerequisite line does not mention `adb`
- [x] 2.3 Verify existing `test_pack_builds_clean_footerless_image` still passes (it asserts `flash.sh` exists; content change is compatible)
