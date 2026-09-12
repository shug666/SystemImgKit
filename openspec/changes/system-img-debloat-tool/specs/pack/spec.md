## ADDED Requirements

### Requirement: Apply deletions then rebuild ext4 from tree
The system SHALL remove the catalog's deletion set from the extracted tree, then SHALL build a fresh ext4 image from the edited tree using `mke2fs -d` with block size 4096 (matching the source) and an inode count sufficient for the remaining files.

#### Scenario: Clean rebuild after deletion
- **WHEN** pack runs with a non-empty deletion set
- **THEN** the selected paths are removed from the tree and `mke2fs -d` produces a fresh ext4 image containing the remaining files

#### Scenario: Empty deletion set still packs
- **WHEN** pack runs with an empty deletion set
- **THEN** the system rebuilds an equivalent ext4 image from the unchanged tree (round-trip)

### Requirement: Restore Android filesystem metadata
The system SHALL re-apply the unpack manifest's metadata to the new image — uid, gid, mode, mtime, hardlinks, SELinux contexts (`security.selinux`), and capabilities (`security.capability`) — via `chown`, `chmod`, `setfattr`, and `setcap` after the image is mounted or via `debugfs` if mounted read-write. Metadata that could not be captured (incomplete manifest) SHALL be skipped with a recorded warning.

#### Scenario: SELinux contexts restored
- **WHEN** pack finalizes the image
- **THEN** files whose manifest recorded a `security.selinux` context have that context re-applied, and any failure is collected into a warnings list surfaced to the user

#### Scenario: Incomplete manifest degrades gracefully
- **WHEN** the manifest was captured via the rootless fallback (incomplete)
- **THEN** pack applies only the metadata it has and reports which files are missing contexts/capabilities

### Requirement: Validate the rebuilt image
The system SHALL run `e2fsck -fy` on the new image and SHALL report the result. The system SHALL refuse to emit a final image if `e2fsck` reports uncorrected errors.

#### Scenario: e2fsck passes
- **WHEN** the rebuilt image is validated
- **THEN** `e2fsck -fy` reports clean and the image is accepted

#### Scenario: e2fsck fails
- **WHEN** `e2fsck -fy` reports uncorrected errors
- **THEN** the system does not produce a final image and surfaces the e2fsck output to the user

### Requirement: Cap image size to the partition
The system SHALL size the new image to fit the edited tree with headroom and SHALL cap it at the original image size (truncated, pre-footer). If the edited tree would require an image larger than the original, the system SHALL refuse to pack with a clear message.

#### Scenario: Image fits partition
- **WHEN** the edited tree produces an image ≤ the original size
- **THEN** the system builds and emits the image

#### Scenario: Tree exceeds partition size
- **WHEN** the edited tree (after deletions) still requires more space than the original image size
- **THEN** the system refuses to pack and reports the size shortfall

### Requirement: Optional sparse output
The system SHALL optionally convert the final raw ext4 to a sparse image via `img2simg` when available and requested. Sparse is opt-in; raw ext4 is the default.

#### Scenario: Sparse output requested
- **WHEN** the user requests sparse output and `img2simg` is available
- **THEN** the system emits a `.img.sparse` in addition to (or instead of) the raw image

#### Scenario: img2simg unavailable
- **WHEN** sparse output is requested but `img2simg` is not installed
- **THEN** the system falls back to raw output and informs the user

### Requirement: Emit AVB Strategy A deployment artifacts
The system SHALL emit a footerless raw ext4 image (no `AVBf` footer) and SHALL generate a `flash.sh` script that flashes `system_new.img` and the user's existing `vbmeta.img` with verification disabled. The system SHALL NOT attempt to re-sign or modify `vbmeta.img`.

#### Scenario: Flash script generated
- **WHEN** pack completes successfully
- **THEN** a `flash.sh` is produced containing `fastboot flash system <img>` and `fastboot --disable-verification flash vbmeta <vbmeta>`, plus a `fastboot reboot`

#### Scenario: No avbtool dependency
- **WHEN** pack runs
- **THEN** the system does not invoke `avbtool`, does not require any keys, and does not append an AVB footer to the output image
