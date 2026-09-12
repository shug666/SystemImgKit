## 1. Project Setup

- [x] 1.1 Scaffold Python package `systemimgkit` with `pyproject.toml` (Python ≥3.12), declare PySide6 + click/typer deps, define console-script entry point `systemimgkit`
- [x] 1.2 Create module layout: `unpack.py`, `catalog.py`, `pack.py`, `avb.py`, `manifest.py`, `cli.py`, `gui/`
- [x] 1.3 Add a dependencies-check helper that probes for `debugfs`, `mke2fs`, `e2fsck`, `dumpe2fs`, `tune2fs`, `rsync`, `img2simg` and reports missing tools
- [x] 1.4 Add a configurable workspace-path module with free-space precheck (source size + headroom threshold)

## 2. Unpack

- [x] 2.1 Implement image format detection: read superblock magic at 0x438 (ext4), tail magic `AVBf`; reject sparse (`0x3aed`) / EROFS with a clear error
- [x] 2.2 Implement AVB footer parser: extract `original_image_size` from the footer, validate against ext4 superblock block count, produce a `.orig` backup and a footerless truncated working copy
- [x] 2.3 Implement root-gated read-only loop mount (via `pkexec`/`sudo` helper) and `rsync -aHAX --numeric-ids` extraction to the workspace tree
- [x] 2.4 Implement metadata manifest dump (JSON): per-file path/type/mode/uid/gid/mtime/size/hardlink/SELinux context/capabilities; walk mounted fs (or `debugfs` for rootless)
- [x] 2.5 Implement rootless `debugfs rdump` fallback; set manifest `incomplete=true` and warn
- [x] 2.6 Verify source image is never opened read-write; add a test asserting the source file's mtime/size is unchanged after unpack

## 3. Catalog & Guard-list

- [x] 3.1 Implement tree walker over the six app directories, producing entries with partition/privilege tags, recursive size, and file count
- [x] 3.2 Create versioned guard-list data file (`guardlist.yaml`) with a generic list + ZUI overlay; mark non-overridable core subset
- [x] 3.3 Implement guard enforcement: locked entries cannot be selected; risk-override toggle unlocks non-core entries and logs overrides; core stays locked
- [x] 3.4 Implement protected-system-path guarding for the Files view (`/apex`, `/system_dlkm`, `/odm_dlkm`, `/firmware`, `/init`, `/bin`, `/lib`, `/lib64`)
- [x] 3.5 Implement search/filter by name, partition, privilege
- [x] 3.6 Implement deletion-set recording as an ordered path list consumable by pack

## 4. Pack

- [x] 4.1 Apply deletion set to a copy of the extracted tree (never the original tree)
- [x] 4.2 Compute target image size from edited tree size + headroom, capped at original (pre-footer) size; refuse if exceeded
- [x] 4.3 Build fresh ext4 via `mke2fs -d <tree>` with block size 4096 and sufficient inodes
- [x] 4.4 Restore manifest metadata: mount new image (or use `debugfs`), apply `chown`/`chmod`/`setfattr` (security.selinux)/`setcap`; collect and surface failures
- [x] 4.5 Run `e2fsck -fy`; refuse to emit final image on uncorrected errors; report clean result
- [x] 4.6 Optional `img2simg` sparse conversion; graceful fallback if tool missing
- [x] 4.7 Generate `flash.sh` (Strategy A: `fastboot flash system`, `fastboot --disable-verification flash vbmeta`, `fastboot reboot`); no avbtool, no footer appended
- [x] 4.8 Verify output image has no `AVBf` footer (tail magic check) and is `e2fsck`-clean

## 5. AVB Module

- [x] 5.1 Implement footer strip + restore helpers; document that v1 ships Strategy A only and that B/C (re-sign) are deferred
- [x] 5.2 Add a guard/assertion that pack never invokes `avbtool` or appends an AVB footer

## 6. CLI

- [x] 6.1 Implement `systemimgkit unpack <img> --workspace <dir>` with progress to stdout
- [x] 6.2 Implement `systemimgkit catalog <workspace> [--list] [--json]` (dry-run listing of apps + guard status)
- [x] 6.3 Implement `systemimgkit pack <workspace> --deletions <file> --out <img> [--sparse]`
- [x] 6.4 Wire dependencies-check and workspace free-space precheck into the CLI entry path

## 7. GUI (PySide6)

- [x] 7.1 Build main window: open-image panel, action buttons (Unpack/Catalog/Pack), status bar
- [x] 7.2 Implement `QThread` worker base class wrapping `subprocess.Popen` with stderr-driven progress and cancellation
- [x] 7.3 Implement catalog tree view (grouped by partition/privilege) with tri-state checkboxes, guard markers, per-entry size, and reclaimed-size total
- [x] 7.4 Implement Files view for arbitrary deletion with protected-path guarding
- [x] 7.5 Implement risk-override toggle with confirmation dialog and override logging
- [x] 7.6 Implement warning/error surfacing panel (metadata fidelity, e2fsck, size-cap, missing deps)

## 8. Testing & Validation

- [x] 8.1 Unit tests: AVB footer parse/strip, format detection, guard-list enforcement, deletion-set recording
- [x] 8.2 Integration test: unpack the real `system.img` → catalog → delete one known-bloat app → pack → `e2fsck` clean + footerless
- [x] 8.3 Round-trip test: unpack → pack with empty deletion set → assert equivalent tree (file set + manifest parity)
- [x] 8.4 Assert source image is byte-identical before/after the full pipeline (never modified in place)
- [ ] 8.5 Manual smoke test of the GUI against the real image (open, unpack, select deletions, pack, inspect `flash.sh`). _Requires `pip install PySide6`; run `systemimgkit gui`, open the real system.img, unpack into a ~25 GB workspace, catalog, tick a deletable bloat app (e.g. `facebook-appmanager`), pack to `system_new.img`, verify `flash.sh` is generated and `e2fsck` reports clean._
