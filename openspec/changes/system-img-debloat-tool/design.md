## Context

The target image is a Lenovo ZUI 18.5 (Android 13/A17) **system-as-root** `system.img`:

- **Format**: raw (non-sparse) ext4, 11.6 GB, block size 4096, inode size 256.
- **Filesystem features**: `shared_blocks` (block-level dedup) — the build system made identical files share physical blocks. In-place editing via a r/w loop mount corrupts *other* files that share a block, and `e2fsck` will refuse such a mount. The safe approach is **rebuild-from-tree**, never in-place edit.
- **AVB**: an appended `AVBf` footer carrying a hash tree, plus a separate 64 KB `vbmeta.img` holding the root hash and its signature. Any byte change in `system.img` invalidates the stored root hash → device refuses to boot unless the bootloader is unlocked and verification disabled.
- **Layout**: the ext4 root *is* the Android root; `/system`, `/product`, `/system_ext`, `/odm`, `/odm_dlkm`, `/system_dlkm`, `/apex`, `/lenovocust`, etc. all live in one image. Pre-installed APKs live in six directories: `/system/app`, `/system/priv-app`, `/product/app`, `/product/priv-app`, `/system_ext/app`, `/system_ext/priv-app`. `priv-app` entries are privileged (GMS Core, SetupWizard, ZuiSystemUI, system providers) — removing the wrong ones bricks the device.

Environment: Linux-only host (ext4 loop-mount available), Python 3.12, e2fsprogs present (`debugfs`, `mke2fs` with `-d`, `e2fsck`, `dumpe2fs`, `tune2fs`). `avbtool` is **not** installed and is intentionally not bundled for v1.

## Goals / Non-Goals

**Goals:**
- One-click (or one-command) unpack of a system-as-root ext4 `system.img` into an editable file tree + metadata manifest, without corrupting `shared_blocks`.
- A browsable, checkable catalog of pre-installed APKs with a guard-list that prevents deleting apps whose removal bricks the OS.
- Clean repack into a flashable `system_new.img` (raw ext4, optionally sparse) that preserves Android filesystem semantics (uid/gid/mode/xattrs/SELinux/caps).
- An AVB deployment path that works on a user-owned unlocked bootloader **without** needing manufacturer keys or `avbtool`: Strategy A (raw ext4, no footer; disable verification via fastboot).
- A PySide6 desktop GUI plus a CLI entry point, Linux-only, with real progress reporting for multi-GB operations.

**Non-Goals:**
- EROFS images, `super.img` / dynamic-partition layouts, `boot`/`vendor`/`odm` as separate images.
- AVB re-signing (Strategies B/C — bundling `avbtool` and key management). Documented as a future enhancement only.
- Performing or automating bootloader unlock. The user unlocks their own device.
- Modifying APEX modules, kernel modules (`*_dlkm`), or firmware — these are read-only during catalog/edit and excluded from the deletion set.

## Decisions

### D1. Rebuild-from-tree, never in-place edit
**Choice**: unpack to a plain directory tree + manifest, edit the tree, `mke2fs -d` a brand-new image.
**Rationale**: `shared_blocks` makes in-place r/w mount unsafe. Rebuilding also lets us shrink the image and guarantees a clean, `e2fsck`-passing result.
**Alternatives**: r/w loop-mount + `rm` (rejected — corrupts shared blocks; needs `e2fsck` to "repair" by duplicating blocks, fragile and size-bloating).

### D2. Metadata capture via read-only loop mount (root-gated)
**Choice**: unpack mounts the image **read-only** (needs root, via `pkexec`/`sudo` for that step only), then `rsync -aHAX --numeric-ids` the tree out and dumps a JSON manifest of uid/gid/mode/mtime/xattrs/SELinux/security.capability. Extraction itself runs unprivileged.
**Rationale**: read-only mount preserves `shared_blocks` (no dedup break), and `rsync -HAX` is the canonical way to capture hardlinks, ACLs, xattrs, and sparse files. The manifest is needed because `mke2fs -d` does not store SELinux contexts or capabilities; we re-apply them post-build with `setfattr`/`setcap`/`chown`/`chmod`.
**Alternatives**:
- `debugfs rdump` (rootless) — works but loses some xattr/cap fidelity and handles large trees slowly; kept as a fallback when root is unavailable.
- Full `debugfs` scripted metadata dump — more code, same fidelity risk.

### D3. AVB Strategy A by default; footer stripped on unpack
**Choice**: unpack detects and strips the `AVBf` footer (truncate `system.img` to `original_image_size` stored in the footer) before mounting. Pack emits a footerless raw ext4. Deployment uses the user's existing `vbmeta.img` flashed with `fastboot --disable-verification`.
**Rationale**: no `avbtool`/keys needed; works on any unlocked bootloader; minimal tool surface. The AVB footer is self-describing (it records the original image size), so stripping is lossless and reversible.
**Alternatives**:
- Re-sign with `avbtool` (B/C) — rejected for v1; needs bundling `avbtool` + key management, no benefit on an unlocked device.
- Leave footer untouched — impossible; the hash tree covers the exact bytes.

### D4. Guard-list for safe deletion
**Choice**: a built-in, curated deny-list of package directory names whose removal is known to brick or destabilize the OS (e.g. `GmsCore`, `GoogleServicesFramework`, `SetupWizard`, `ZuiSystemUI`, `SettingsProvider`, `TelephonyProvider`, `SystemUI`-class apps, mainline module APEX). The catalog marks these as locked/⛔ and refuses selection; power users can override via an explicit "I accept the risk" toggle that logs the override.
**Rationale**: the `priv-app` set contains apps the OS cannot boot without. A guided guard-list turns a footgun into a safe default while still allowing advanced removal.
**Alternatives**: no guard-list (rejected — too easy to brick); hardcoded full block (rejected — removes legitimate debloat like `facebook-appmanager`, `OperaProvider`).

### D5. Catalog classification and search
**Choice**: catalog walks the app directories — the standard AOSP six (`/system/app`, `/system/priv-app`, `/product/app`, `/product/priv-app`, `/system_ext/app`, `/system_ext/priv-app`) **plus ZUI's `/system/preinstall`**, where this OEM concentrates its bundled/bloat apps (Instagram, CapCut, Adobe LightRoom, Opera, YouTubeKids, PlayGames, …). It sizes each app directory recursively, groups entries by partition (`system`/`product`/`system_ext`), exposes search/filter, and shows a per-entry size + guard status. Non-APK arbitrary-file deletion (e.g. ringtones, wallpapers) is supported in the "Files" tab by browsing the full tree, but defaults to the APK list.
**Rationale**: most users want "remove YouTube/Chrome/Facebook"; on ZUI the bulk of bloat lives in `/system/preinstall` rather than the standard `app`/`priv-app` dirs, so omitting it would miss the primary debloat targets. A few users want to drop wallpapers. One catalog, two views.

### D6. Repack target sizing
**Choice**: build the new ext4 with the same block size (4096) and inode count as the source, sized to fit the edited tree (computed from tree size + headroom), capped at the original image size so it still fits the partition. Run `e2fsck -fy` and report any errors. Optional `img2simg` for sparse output (smaller flash).
**Rationale**: matching block size keeps it drop-in compatible; capping at original size guarantees the partition still holds it.
**Alternatives**: fixed large size (wastes space, may exceed partition).

### D7. Tech stack: PySide6 + QThread workers
**Choice**: PySide6 GUI; all long operations run in `QThread` workers that drive `subprocess.Popen` and parse stderr for progress; a `pyproject.toml`-defined CLI mirrors the GUI actions for scripting. Packaged as a Python app (no native compilation); distribution via `pipx`/venv, not a binary installer, for v1.
**Rationale**: all heavy lifting is already CLI tools (`debugfs`, `mke2fs`, `e2fsck`, `rsync`); Python only orchestrates. PySide6 gives native tree widgets with checkboxes and clean threading. CLI ensures the pipeline is automatable and testable without the GUI.
**Alternatives**: Tauri/Electron (rejected — adds a JS/TS toolchain for no benefit since no native data code is needed); Tkinter (rejected — weak tree widgets and threading UX for multi-GB work).

## Risks / Trade-offs

- **[Metadata fidelity loss on rootless fallback]** → `debugfs rdump` path may miss SELinux contexts/caps. Mitigation: warn the user; recommend the root-gated RO-mount path; the manifest carries an `incomplete` flag if captured via fallback, and pack re-applies only what it has.
- **[Wrong guard-list entry removed via override]** → device bootloops. Mitigation: override requires explicit confirmation + logs the action; docs document a `fastboot boot`/recovery reflash path. Non-overridable core subset (SystemUI/providers) stays locked even with override on in v1.
- **[Image larger than partition]** → fastboot flash fails. Mitigation: cap new image size at original `system.img` size; refuse to pack if the edited tree exceeds it (with `shared_blocks` removed, the tree is usually *smaller*).
- **[selinux context restore fails post-build]** → mislabeled files may break app permissions. Mitigation: `setfattr` errors are collected and surfaced; recommend `restorecon`-equivalent via the manifest's recorded contexts.
- **[AVB footer mis-parse]** → truncating too much corrupts ext4. Mitigation: footer parse is validated against the ext4 superblock's reported size and `e2fsck -n` dry run before the truncation is committed; keep a `.orig` copy.
- **[sudo/pkexec friction]** → user may lack polkit. Mitigation: support a manual `sudo` invocation; if neither works, fall back to rootless `debugfs rdump` with a fidelity warning.
- **[Future ZUI updates change layout]** → guard-list may miss a new critical app. Mitigation: guard-list is a versioned data file, not hardcoded; documented to update per OEM release.

## Migration Plan

Not applicable (greenfield tool). Rollback for a flashed device: re-flash the original `system.img` + `vbmeta.img` via fastboot from a kept backup. The tool always preserves an unmodified copy of the source image and never writes in place.

## Open Questions

- Should sparse output (`img2simg`) be the default, or raw? (Leaning: raw default, sparse opt-in — simpler, and fastboot accepts both.)
- Should the guard-list ship per-OEM profiles (Lenovo/ZUI now, others later), or one generic list + overrides? (Leaning: one generic with a ZUI-specific overlay for v1.)
- Where to store the work tree for an 11 GB image (default temp dir may be too small)? Needs an explicit, user-configurable workspace path with a free-space precheck.
