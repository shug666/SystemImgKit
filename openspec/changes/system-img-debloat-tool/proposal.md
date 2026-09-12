## Why

Modifying a stock Android `system.img` (here a Lenovo ZUI 18.5 A17 system-as-root ext4 image) to remove bundled/bloat apps is error-prone: the image uses block-level dedup (`shared_blocks`) that breaks naive in-place edits, and it carries an appended AVB (Android Verified Boot) hash-tree footer plus a `vbmeta.img` whose root hash must match or the device refuses to boot. There is no desktop tool that performs the full unpack → edit → repack → re-flash cycle safely. This change delivers that tool.

## What Changes

- New **unpack** capability: strip the appended AVB footer, mount the raw ext4 read-only, and extract a file tree plus a metadata manifest (uid/gid/mode/xattrs/SELinux contexts/capabilities) preserving Android filesystem semantics.
- New **catalog** capability: walk the extracted tree and present the six app directories (`/system/app`, `/system/priv-app`, `/product/app`, `/product/priv-app`, `/system_ext/app`, `/system_ext/priv-app`) as a checkable list, with a guard-list that protects apps whose removal bricks the device (GMS Core, SetupWizard, ZuiSystemUI, system providers).
- New **edit** capability: delete selected APK directories/files from the tree and record the deletion set.
- New **pack** capability: rebuild a fresh ext4 image from the edited tree with `mke2fs -d`, restore the manifest metadata, run `e2fsck -fy`, and optionally convert to sparse.
- New **avb** capability: handle verified boot by emitting an AVB strategy. Default (Strategy A) produces a raw ext4 image with no footer and a generated flash script that disables verification on an unlocked bootloader; re-signing (Strategies B/C) is explicitly out of scope for v1.
- New **gui** capability: a PySide6 desktop application (Linux-only) that orchestrates unpack → catalog → edit → pack with progress reporting, plus a CLI entry point for scripted use.
- **BREAKING**: none (greenfield tool; no existing behavior to break).

## Capabilities

### New Capabilities
- `unpack`: safely convert a raw ext4 system.img (system-as-root, with AVB footer) into an editable file tree plus a metadata manifest.
- `catalog`: enumerate APKs/files across the six app directories, classify them, and enforce a safe-delete guard-list.
- `pack`: rebuild a clean ext4 image from the edited tree, restore Android metadata, and validate with e2fsck; produce AVB-deployment artifacts and a flash script.
- `gui`: PySide6 desktop application and CLI entry point that wires unpack/catalog/pack together for end users.

### Modified Capabilities
<!-- None — greenfield. -->

## Impact

- **Dependencies**: `e2fsprogs` (debugfs, mke2fs, e2fsck, dumpe2fs, tune2fs), `rsync`, `img2simg` (optional, via android-sdk-libsparse-utils), `mount`/`losetup` (via sudo/pkexec). Python 3.12+, PySide6.
- **System access**: unpack requires read-only loop-mount of the image → root privileges for that step only (delegated via sudo/pkexec). Tree extraction and repack run unprivileged.
- **Artifacts produced**: `system_new.img` (raw or sparse ext4), a regenerated `vbmeta` flash instruction (Strategy A), and a `flash.sh` script.
- **Out of scope (v1)**: EROFS images, super.img handling, dynamic partitions, AVB re-signing with keys, non-system partitions (boot, vendor, odm as separate images).
- **Ethics/safety**: the tool rebuilds an image for the user's own unlocked device. It performs no bootloader unlock or verification bypass itself; flashing with `--disable-verification` is a documented fastboot operation the user runs on their own device.
