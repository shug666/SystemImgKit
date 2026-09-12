## ADDED Requirements

### Requirement: Enumerate pre-installed apps across app directories
The system SHALL walk the app directories — `/system/app`, `/system/priv-app`, `/system/preinstall` (ZUI bundled apps), `/product/app`, `/product/priv-app`, `/system_ext/app`, `/system_ext/priv-app` — within the extracted tree and SHALL present each app directory as a catalog entry grouped by partition and privilege level.

#### Scenario: Catalog lists all app directories
- **WHEN** the catalog is built from an extracted tree
- **THEN** every directory under the app paths appears as an entry, tagged with its partition (`system`/`product`/`system_ext`) and privilege (`app`/`priv-app`/`preinstall`)

#### Scenario: Per-entry sizing
- **WHEN** a catalog entry is displayed
- **THEN** the system shows the recursive size of that app directory and the count of files it contains

### Requirement: Apply a safe-delete guard-list
The system SHALL maintain a versioned guard-list of app directory names whose removal is known to brick or destabilize the OS. Guarded entries SHALL be marked locked (⛔) and SHALL NOT be selectable for deletion by default. A non-overridable core subset SHALL remain locked even when risk-override is enabled.

#### Scenario: Guarded app cannot be selected
- **WHEN** a user attempts to select a guarded app directory (e.g. `GmsCore`, `SetupWizard`, `ZuiSystemUI`)
- **THEN** the system prevents selection and shows the guard reason

#### Scenario: Risk override unlocks non-core guarded apps
- **WHEN** the user enables the explicit "I accept the risk" toggle
- **THEN** guarded entries outside the non-overridable core subset become selectable, the override is logged, and core entries remain locked

#### Scenario: Guard-list is data-driven and versioned
- **WHEN** the tool loads the guard-list
- **THEN** it reads from a versioned data file (with an optional ZUI overlay) rather than hardcoded values, so it can be updated per OEM release

### Requirement: Support arbitrary file deletion
The system SHALL provide a "Files" view that browses the full extracted tree (not only app directories) and allows selecting arbitrary files or directories for deletion, with the same guard mechanism applied to protected system paths (`/apex`, `/system_dlkm`, `/odm_dlkm`, `/firmware`, `/init`, `/bin`, `/lib`, `/lib64`).

#### Scenario: Protected system paths are guarded
- **WHEN** a user browses the Files view
- **THEN** the protected system paths are marked locked and cannot be selected for deletion

### Requirement: Search and filter
The system SHALL support searching/filtering the catalog by app name and SHALL support filtering by partition and privilege level.

#### Scenario: Filter to product apps only
- **WHEN** the user filters to `product` partition
- **THEN** only entries under `/product/app` and `/product/priv-app` are shown

### Requirement: Record the deletion set
The system SHALL record the selected deletion set as an ordered list of tree paths and SHALL make it available to the pack stage.

#### Scenario: Deletion set passed to pack
- **WHEN** the user proceeds to pack after selecting entries
- **THEN** the recorded deletion set is the exact input the pack stage uses to remove entries from the tree before rebuilding the image
