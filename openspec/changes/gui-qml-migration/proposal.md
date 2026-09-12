## Why

The current `gui` capability is implemented with PySide6 **QtWidgets** — a 391-line imperative `mainwindow.py` that hand-assembles `QGroupBox`/`QTreeWidget`/`QTabWidget` widgets. The resulting interface reads as dated and dense: thick bezels, flat list rows, no hover/transition polish, and a layout density that cannot be improved without rewriting the view code. The pain point is purely **visual**: the backend (unpack/catalog/pack/avb + QThread workers) is correct and decoupled. Migrating the presentation layer to **QtQuick (QML)** with card-style delegates gives the tool a modern appearance and separates view from logic, while leaving all operational behavior unchanged.

## What Changes

- Replace the QtWidgets presentation layer (`gui/mainwindow.py`, `gui/app.py`) with a **QtQuick (QML)** UI: `main.qml` driven by a `QQmlApplicationEngine`, using QtQuick.Controls 2 with the **Universal** theme as a base.
- Render the app catalog as a **card-style `ListView`** with a custom delegate (checkbox + name + partition + size + file-count), replacing the `QTreeWidget` 6-column table. Guard level is expressed via color/badge rather than a column.
- Introduce an **`AppCardModel`** (`QAbstractItemModel`) that exposes catalog entries as model roles and owns the guard/selection rules in the Python layer — the QML view only renders and forwards user intent.
- Introduce a **`Controller`** (`QObject`) bridging QML and the core operations: image open, unpack/catalog/pack invocation, risk-override state, and worker lifecycle. `Worker`/`QThread`/signals are reused as-is.
- Re-express the "Files (advanced)" view as a compact `ListView` (not cards) over a `FileTreeModel`, keeping the protected-path guard in the model layer.
- Move dev-time QML loading from the filesystem and add a `qrc` packaging step for distribution.
- **BREAKING**: none externally — the CLI entry point (`systemimgkit` → `cli:main`) is untouched and the operational contract (open → unpack → catalog → select → pack) is preserved. The breakage is internal-only: `gui/mainwindow.py` and the QtWidgets UI are removed.

## Capabilities

### New Capabilities
<!-- None — no new capability. -->

### Modified Capabilities
- `gui`: the presentation layer changes from QtWidgets to QtQuick (QML) with card-style delegates and a model-driven architecture; operational requirements (open/unpack/catalog/select/pack, guard-list protection, progress/cancel, CLI parity) are preserved. Spec deltas reflect the QML view structure, the model-owned guard rules, and the Universal-theme card-delegate appearance.

## Impact

- **Code**: `systemimgkit/gui/` rewritten — `app.py` swaps `QApplication`+`QMainWindow` for `QApplication`+`QQmlApplicationEngine`; `mainwindow.py` is replaced by `main.qml` + `AppCardModel` + `Controller`; `workers.py` reused with safe-shutdown. New `gui/qml/` resource tree, `gui/rootops.py`, `gui/controller.py`, `gui/models.py` (AppCardModel + FileTreeModel + BigFileModel).
- **New files**: `root_helper.py` (root subprocess for unpack/pack), `ext4tools/linux-x86_64/{mke2fs,e2fsdroid}` (Android e2fsprogs, static-linked), `gui/rootops.py`, `gui/controller.py`, `gui/models.py`.
- **Dependencies**: none added — PySide6 (already a dependency) ships QtQuick, Controls 2, and the Universal theme. Android e2fsdroid/mke2fs bundled (no system install needed).
- **Reused as-is**: `catalog`, `avb`, `workspace`, `imagefmt`, `runner`/`CancelToken`, `cli.py`. `unpack` and `pack` extended (not rewritten) with superblock probing, shared_blocks detection, SELinux capture/restore via file_contexts, target_blocks.
- **Security posture unchanged**: guard-list protection (core locked, guarded needs override) remains enforced in the Python model/controller layer — QML never authorizes a deletion.
- **Scope expansion beyond original view-layer migration**: normal-user GUI + root helper (D8), shared_blocks e2fsdroid rebuild (D9), SELinux via file_contexts (D10), symlink xattr fix (D11), target partition size (D12), hardlink-aware _du (D13), big-file view, auto-catalog-after-unpack, updated flash.sh.
