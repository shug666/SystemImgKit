## ADDED Requirements

### Requirement: Release workflow builds a portable package for Ubuntu 20.04.6
The system SHALL provide a GitHub Actions workflow that freezes the SystemImgKit GUI into a self-contained portable package runnable on Ubuntu 20.04.6 x86_64 with no local Python or Qt toolchain. The workflow SHALL build inside a `container: ubuntu:20.04` on an `ubuntu-latest` job so the frozen artifacts are linked against glibc 2.31 and therefore compatible with 20.04.6. The workflow SHALL install Python 3.12 (via the deadsnakes PPA), PySide6, PyYAML, and PyInstaller in the container, then produce a PyInstaller `onedir` bundle containing the GUI entry, the bundled ext4 tools, the guardlist YAML, the `.desktop` file, and icon resources.

#### Scenario: Package runs on Ubuntu 20.04.6 without a local toolchain
- **WHEN** the release `tar.gz` is extracted on a clean Ubuntu 20.04.6 x86_64 host whose only prerequisite was running `install-deps.sh`
- **THEN** launching the bundled `systemimgkit` executable starts the PySide6 QML GUI successfully, without the host having Python 3.12 or PySide6 installed

#### Scenario: Build container pins the glibc baseline
- **WHEN** the workflow runs
- **THEN** the PyInstaller step executes inside a `container: ubuntu:20.04` (glibc 2.31), not directly on the `ubuntu-latest` host, so frozen binaries do not require a newer glibc than 20.04.6 provides

#### Scenario: Bundled data files are present in the package
- **WHEN** the frozen package is inspected
- **THEN** it contains the precompiled `mke2fs` and `e2fsdroid` binaries (executable), `guardlist.yaml`, the `.desktop` file, and the icon resource tree

### Requirement: Two frozen entry executables
The workflow SHALL freeze two separate entry executables in one `onedir` bundle: `systemimgkit` (the GUI, `systemimgkit.gui.app.main`) and `root_helper` (the headless privileged helper, `systemimgkit.root_helper.main`). The root helper SHALL NOT pull PySide6 into its bundle.

#### Scenario: GUI and helper are sibling executables
- **WHEN** the `onedir` bundle is produced
- **THEN** it contains both `systemimgkit` and `root_helper` as executable files in the same directory, so the GUI can resolve and invoke the helper by relative path

### Requirement: QML runtime dependencies are bundled
The PyInstaller spec SHALL declare the QML engine hidden-imports required at runtime — at minimum `QtQuick`, `QtQuick.Controls`, `QtQuick.Layouts`, `QtQuick.Dialogs`, `QtQuick.Effects`, and `QtQml.Models` — so the frozen GUI does not fail with "module is not installed" errors.

#### Scenario: GUI renders after freezing
- **WHEN** the frozen `systemimgkit` is launched and the QML engine loads `main.qml`
- **THEN** all QML imports resolve (`QtQuick`, `QtQuick.Controls`, `QtQuick.Layouts`, `QtQuick.Dialogs`, `QtQuick.Effects`) and the application window renders without a "module not installed" error

### Requirement: Release artifacts are published to GitHub Release
The workflow SHALL trigger on tags matching `v*` and on manual `workflow_dispatch`. On a tag trigger it SHALL create a GitHub Release and upload the portable `tar.gz` and `install-deps.sh` as release assets. The `tar.gz` SHALL extract to a single top-level directory.

#### Scenario: Tag produces a downloadable release
- **WHEN** a `v*` tag is pushed
- **THEN** the workflow builds the package and attaches `SystemImgKit-<tag>-ubuntu-20.04-x86_64.tar.gz` and `install-deps.sh` to the GitHub Release for that tag

#### Scenario: Manual dispatch for iteration
- **WHEN** the workflow is triggered via `workflow_dispatch`
- **THEN** it runs the build and uploads the artifacts as workflow artifacts (without requiring a tag), so builds can be iterated before tagging

### Requirement: Host runtime dependency installer ships with the package
The workflow SHALL generate or include an `install-deps.sh` that installs the host-level runtime dependencies the frozen package cannot bundle: `e2fsprogs`, `rsync`, `img2simg` (android-tools-fsutils or equivalent), `adb`, `fastboot`, `policykit-1`, and the Qt6 GUI runtime libraries (`libgl1`, `libegl1`, `libxkbcommon0`, `libdbus-1-3`). The script SHALL be idempotent and apt-based.

#### Scenario: User installs host deps before first run
- **WHEN** the user runs `install-deps.sh` on Ubuntu 20.04.6
- **THEN** it installs the listed packages via `apt` and may be re-run safely, leaving the system ready to run the frozen GUI and its pkexec root-privilege chain
