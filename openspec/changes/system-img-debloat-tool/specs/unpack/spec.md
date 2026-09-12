## ADDED Requirements

### Requirement: Detect image format and AVB footer
The system SHALL identify whether the input `system.img` is raw ext4, sparse, or EROFS, and SHALL detect the presence of an appended AVB footer (`AVBf` magic). For v1 the system SHALL accept raw ext4 only and SHALL reject sparse/EROFS with a clear error.

#### Scenario: Raw ext4 image with AVB footer
- **WHEN** the input is a raw ext4 system-as-root image with an `AVBf` footer
- **THEN** the system detects ext4 via the superblock magic at offset 0x438 and detects the `AVBf` footer at the file tail, and proceeds to unpack

#### Scenario: Unsupported image format
- **WHEN** the input is a sparse image or EROFS image
- **THEN** the system rejects it with a message naming the unsupported format and does not modify the file

### Requirement: Strip AVB footer losslessly
The system SHALL parse the `AVBf` footer to obtain the original image size and SHALL produce a footerless copy of the image truncated to that size before mounting. The system SHALL preserve the original unmodified image unchanged.

#### Scenario: Footer stripped before mount
- **WHEN** unpack runs on an image with an AVB footer
- **THEN** the system creates a working copy truncated to the original image size recorded in the footer, validates it against the ext4 superblock, and mounts the truncated copy — never the footer-bearing original

#### Scenario: Footer already absent
- **WHEN** the input image has no AVB footer
- **THEN** the system skips stripping and proceeds to mount directly, reporting that no footer was found

### Requirement: Extract file tree preserving Android semantics
The system SHALL extract the image contents into a plain directory tree and SHALL capture a metadata manifest recording, for every file: path, type, mode, uid, gid, mtime, size, hardlink target, SELinux context (`security.selinux` xattr), and capability bits (`security.capability` xattr). The system SHALL preserve hardlinks as hardlinks in the tree.

#### Scenario: Root-gated read-only mount extraction
- **WHEN** root privileges are available (via sudo/pkexec)
- **THEN** the system mounts the truncated image read-only and copies the tree with `rsync -aHAX --numeric-ids`, producing a tree plus a complete manifest

#### Scenario: Rootless fallback extraction
- **WHEN** root privileges are unavailable
- **THEN** the system falls back to `debugfs rdump`, extracts the tree, and marks the manifest as `incomplete=true` with a warning that SELinux contexts/capabilities may be partially captured

### Requirement: Do not corrupt shared_blocks
The system SHALL NOT mount the image read-write during unpack and SHALL NOT modify the source image in place. All extraction is read-only so block dedup (`shared_blocks`) is never broken.

#### Scenario: Read-only access only
- **WHEN** unpack extracts the tree
- **THEN** the source image is opened read-only, no block is written, and the original `shared_blocks` feature remains intact on the source

### Requirement: Workspace and free-space handling
The system SHALL use a user-configurable workspace directory for the working copy and extracted tree, and SHALL verify sufficient free space (source size + tree size headroom) before starting, failing fast with a clear message if space is insufficient.

#### Scenario: Insufficient free space
- **WHEN** the workspace has less free space than the required threshold
- **THEN** the system reports the missing amount and aborts before creating any large files
