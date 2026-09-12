## MODIFIED Requirements

### Requirement: Catalog view with checkboxes and guard indicators
The catalog SHALL be rendered as a **card-style `ListView`** (one card per app directory) using QtQuick.Controls 2, with a checkbox, app name, partition, privilege, recursive size, and file-count on each card. Guard level SHALL be expressed via a color/badge on the card (core = locked-red, guarded = amber, deletable = default) rather than a text column. Sorting SHALL be offered via a control in the view (by name, size, or guard level) rather than a clickable column header. The card list SHALL be driven by a `QAbstractItemModel` (`AppCardModel`); the view only renders model data and forwards user selection intent. Selecting a deletable app adds it to the deletion set; guarded/core cards resist selection with the guard reason shown as a tooltip/badge.

#### Scenario: Select a deletable app
- **WHEN** the user checks `YouTube` under `/product/app`
- **THEN** the entry is added to the deletion set and the total reclaimed size updates

#### Scenario: Guarded entry resists selection
- **WHEN** the user attempts to check `GmsCore`
- **THEN** the checkbox does not activate and the card shows the guard reason as a tooltip/badge

#### Scenario: Sort the catalog
- **WHEN** the user picks "size" in the sort control
- **THEN** the card list reorders by descending recursive size without re-querying the catalog

## ADDED Requirements

### Requirement: Guard rules enforced in the data model layer
The safe-delete guard rules (core entries always locked; guarded entries require risk-override) SHALL be enforced in the Python `AppCardModel`/`Controller` layer. The QML view SHALL NOT be able to authorize the selection or deletion of a core or (without override) a guarded entry, regardless of any view-side state; the model rejects such selections and the view reflects the rejected state.

#### Scenario: Core entry cannot be selected even from the view
- **WHEN** the QML delegate flips a core entry's checkbox to checked
- **THEN** the model refuses the change, the checkbox reverts to unchecked, and the user is notified that core apps cannot be deleted

#### Scenario: Guarded entry requires override
- **WHEN** the user toggles a guarded entry's checkbox while risk-override is off
- **THEN** the model refuses the selection until the user enables risk-override, at which point the override is logged and the entry becomes selectable

### Requirement: Modern card-style catalog presentation
The catalog `ListView` SHALL use the QtQuick.Controls 2 **Universal** theme as its visual base, with cards showing hover and selection states, readable spacing, and a monospace rendering of size/counts. The presentation layer SHALL be authored in QML (`.qml` files) loaded via a `QQmlApplicationEngine`, separating view from logic.

#### Scenario: Card hover and selection feedback
- **WHEN** the user hovers over a deletable card
- **THEN** the card shows a hover highlight, and checking it shows a distinct selected state

#### Scenario: Image-open panel reflects image metadata
- **WHEN** the user opens a `system.img`
- **THEN** the QML image panel shows the image name, size, detected format, and AVB-footer presence, and enables the Unpack action

### Requirement: Files (advanced) view
The system SHALL provide a "Files" view as a compact `ListView` over the full extracted tree (not only app directories), allowing selection of arbitrary files/directories for deletion, with the same guard mechanism applied to protected system paths. This view SHALL use a denser row delegate than the app cards, since it is an advanced use.

#### Scenario: Protected system paths are guarded
- **WHEN** a user browses the Files view
- **THEN** protected system paths are marked locked and cannot be selected for deletion

### Requirement: Big-file view
The system SHALL provide a "大文件" (big files) view that lists the largest files across the entire extracted tree (capped at ~300 entries, sorted by size descending), with path, size, and guard indicator. Files under a selected app directory SHALL automatically appear checked (deleted with the app). The reclaimable total SHALL include both app deletions and manually-checked big-file deletions.

#### Scenario: Big files listed by size
- **WHEN** the catalog is loaded
- **THEN** the big-file view shows the 300 largest files by size descending

#### Scenario: App selection syncs to big files
- **WHEN** the user selects an app in the catalog view
- **THEN** big files under that app's directory show as checked in the big-file view (deleted with the app)

### Requirement: Target partition size
The system SHALL allow the user to specify a target partition size (in GB) for the rebuilt image, so it fits a device system partition smaller than the original. A "probe device" button SHALL query the connected device via `fastboot getvar partition-size:system_a` and auto-fill the target. When set, the image SHALL be built at the target block count; the tool SHALL NOT allow enlarging beyond the original size.

#### Scenario: Probe device partition
- **WHEN** the user clicks "probe device partition" with a device in fastboot mode
- **THEN** the target size is set to the device's system_a partition size

#### Scenario: Build smaller image
- **WHEN** a target partition size is set smaller than the original
- **THEN** the rebuilt image is sized to fit the target partition

### Requirement: Normal-user GUI with per-operation root helper
The GUI SHALL run as a normal (non-root) user so the native file dialog can access the user's home directory. Root operations (unpack, pack) SHALL be delegated to a `root_helper` subprocess invoked via `pkexec`, communicating via a stdout/stderr protocol (progress on stderr, `SIK_RESULT`/`SIK_ERROR` JSON on stdout). The GUI SHALL NOT do whole-process elevation.

#### Scenario: File dialog reaches user home
- **WHEN** the GUI runs as a normal user
- **THEN** the native file dialog can navigate to the user's home directory and any mounted volume

#### Scenario: Per-operation elevation
- **WHEN** the user triggers unpack or pack
- **THEN** a single pkexec authorization window appears for that operation only

### Requirement: shared_blocks image rebuild with e2fsdroid
When the source image uses the ext4 `shared_blocks` feature (detected via `dumpe2fs -h` at unpack time and stored in the manifest), the pack stage SHALL rebuild using the Android `mke2fs` + `e2fsdroid` toolchain (bundled at `ext4tools/linux-x86_64/`) to reproduce block-level deduplication. `e2fsdroid -e -s -f staging -a / -C fs_config -S file_contexts image` SHALL be used, applying uid/gid/mode/caps via `-C` and SELinux contexts via `-S`. The mount-based `_restore_metadata` SHALL be skipped for shared_blocks images (they refuse rw mounts).

#### Scenario: shared_blocks detected and rebuilt
- **WHEN** the source image has the shared_blocks feature
- **THEN** the pack stage uses Android mke2fs + e2fsdroid with -s (SHARE_DUP) to reproduce dedup, and the output image fits the partition

#### Scenario: Non-shared image uses standard mke2fs
- **WHEN** the source image does not have shared_blocks
- **THEN** the pack stage uses the standard system mke2fs -d path unchanged

### Requirement: SELinux metadata via file_contexts and fs_config
For shared_blocks images, the system SHALL generate a `file_contexts` file (two-column format: regex_path + context, including root `/` and `lost+found`) and a `canned fs_config` file (path uid gid mode [capabilities=N]) from the manifest, passed to e2fsdroid via `-S` and `-C`. The system SHALL capture SELinux contexts for all file types including symlinks (using `os.getxattr` with `follow_symlinks=False`).

#### Scenario: Symlink SELinux context captured
- **WHEN** a symlink like /init is captured during unpack
- **THEN** its security.selinux xattr (e.g. u:object_r:init_exec:s0) is stored in the manifest

#### Scenario: SELinux written via e2fsdroid -S
- **WHEN** a shared_blocks image is rebuilt
- **THEN** all files including symlinks have correct security.selinux xattrs in the output image

### Requirement: Updated flash.sh script
The generated `flash.sh` SHALL include the full flashing sequence: `adb reboot fastboot`, `fastboot erase system`, `fastboot flash system`, `fastboot --disable-verification flash vbmeta` (if vbmeta.img is available next to the source image), commented resize-logical-partition commands for dynamic partitions, and `fastboot -w` + `fastboot reboot`.

#### Scenario: vbmeta auto-detected
- **WHEN** a vbmeta.img exists next to the source image
- **THEN** the flash.sh script references it and disables verification
