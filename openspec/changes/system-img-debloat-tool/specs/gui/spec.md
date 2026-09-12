## ADDED Requirements

### Requirement: PySide6 desktop application
The system SHALL provide a PySide6 (Qt6) desktop application that runs on Linux, presenting a single window to open an image, unpack, browse the catalog, select deletions, and pack.

#### Scenario: Open an image
- **WHEN** the user opens a `system.img`
- **THEN** the application shows the image path, size, detected format, and AVB-footer presence, and enables the Unpack action

### Requirement: Non-blocking long operations with progress
All long operations (unpack, pack, validation) SHALL run in background `QThread` workers. The UI SHALL remain responsive and SHALL show a progress indicator driven by worker subprocess output. The UI SHALL allow the user to cancel an in-progress operation.

#### Scenario: Progress during unpack
- **WHEN** unpack is running
- **THEN** the UI shows a progress bar advanced by parsing the worker's stderr, and the main window stays interactive

#### Scenario: Cancel a running operation
- **WHEN** the user clicks Cancel during a long operation
- **THEN** the worker terminates its subprocess, cleans up partial workspace files, and returns the UI to the idle state

### Requirement: Catalog view with checkboxes and guard indicators
The catalog SHALL be rendered as a tree grouped by partition/privilege, with tri-state checkboxes per app directory, guard (⛔) markers on guarded entries, and per-entry sizes. Selecting a parent selects its deletable children; guarded children remain unselected.

#### Scenario: Select a deletable app
- **WHEN** the user checks `YouTube` under `/product/app`
- **THEN** the entry is added to the deletion set and the total reclaimed size updates

#### Scenario: Guarded entry resists selection
- **WHEN** the user attempts to check `GmsCore`
- **THEN** the checkbox does not activate and a tooltip shows the guard reason

### Requirement: CLI entry point mirrors GUI actions
The system SHALL expose a CLI (`python -m systemimgkit` or a console script) with subcommands for unpack, catalog (list/dry-run), and pack, so the pipeline is scriptable and testable without the GUI.

#### Scenario: CLI unpack then pack
- **WHEN** a user runs `unpack <img> --out <workspace>` then `pack <workspace> --deletions <file> --out system_new.img`
- **THEN** the pipeline runs headless with the same behavior as the GUI and prints progress to stdout

### Requirement: Surface warnings and errors
The system SHALL surface metadata-fidelity warnings, e2fsck errors, size-cap violations, and missing-dependency errors (e.g. `img2simg`, root for mount) to the user clearly, distinguishing warnings from blocking errors.

#### Scenario: Missing root for mount
- **WHEN** unpack cannot acquire root for the read-only mount
- **THEN** the UI/CLI informs the user and offers the rootless fallback with its fidelity caveat
