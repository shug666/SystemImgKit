## Context

The `gui` capability currently presents the SystemImgKit pipeline (open → unpack → catalog → select → pack) through a PySide6 **QtWidgets** UI hand-assembled in `systemimgkit/gui/mainwindow.py` (391 lines): `QGroupBox` panels, two `QTreeWidget`s in a `QTabWidget`, and a `QTextEdit` warning panel. The backend — `unpack`/`catalog`/`pack`/`avb`, the `Workspace`, `imagefmt`, and the `Worker(QThread)` with `progress/finished/failed/cancelled` signals — is correct and cleanly decoupled from the view. The motivation for this change is purely visual: the QtWidgets interface reads as dated and dense, and improving it within QtWidgets (QSS) cannot fix layout density or delegate structure. The migration replaces the presentation layer with **QtQuick (QML)** while reusing 100% of the backend.

Constraint: `system-img-debloat-tool` (the change that built this tool) is at 40/41 tasks and must not be disturbed. This is a separate, view-layer-only change.

## Goals / Non-Goals

**Goals:**
- Replace the QtWidgets presentation layer with a QtQuick (QML) UI using QtQuick.Controls 2.
- Render the app catalog as a card-style `ListView` with a custom delegate; express guard level via color/badge.
- Move catalog data and guard/selection rules into a Python `QAbstractItemModel` (`AppCardModel`); introduce a `Controller` (`QObject`) to bridge QML ↔ core operations.
- Preserve every operational behavior: open/unpack/catalog/select/pack, guard-list protection, progress + cancel, warnings/errors, CLI parity.
- Keep the security posture: deletion authorization lives in Python; QML never authorizes a deletion.

**Non-Goals:**
- No change to `unpack`/`catalog`/`pack`/`avb` logic, `Workspace`, `imagefmt`, `runner`/`CancelToken`, or `Worker`.
- No change to the CLI (`cli.py`) or its entry point.
- No new operational features (no AVB re-signing, no new pack options).
- No cross-platform work beyond Linux (the tool is Linux-only).
- No performance optimization of the image pipeline — the bottleneck is e2fsprogs subprocesses, not rendering.

## Decisions

### D1: QtQuick.Controls 2 with the Universal theme (vs Material / custom palette)
**Choice**: Universal theme as the base.
**Rationale**: Universal is the most desktop-neutral Controls 2 theme — flat, controllable, not mobile-flavored. Material reads as a phone UI on a Linux desktop; a fully custom palette is unjustified scope for a view-layer polish. Universal gives hover/selection/rounding for free and stays themable later.
**Alternatives**: Material (too mobile), full custom palette (over-scope for a polish change), Fusion (QtWidgets-era look — defeats the purpose).

### D2: Card-style `ListView` + custom delegate for the app catalog (vs `TreeView`)
**Choice**: `ListView` with a custom card delegate, one card per app.
**Rationale**: The user's stated pain is "the interface is ugly"; a card list with hover/selection polish has the highest visual upside. The existing 6-column `QTreeWidget` table is the single biggest contributor to the dated feel. Cards drop the dense column grid in favor of a readable row.
**Trade-off**: We lose native clickable sortable column headers. Mitigation → D4 (sort control in the view).
**Alternatives**: Qt 6 `TreeView` (keeps the table feel, lowest visual upside — rejected as it does not address the pain point).

### D3: Guard rules live in the Python `AppCardModel`/`Controller`, not in QML
**Choice**: `AppCardModel.flags()`/`setData()` and the `Controller` (which holds risk-override state) enforce core-locked and guarded-needs-override rules. QML delegates only render the model's `guard` role and forward checkbox intents; the model rejects illegal selections and the view reflects the reverted state.
**Rationale**: The guard-list exists to prevent bricking the device — it is a safety rule, not a presentation rule. Letting QML decide authorizability means anyone editing `.qml` could bypass protection. Keeping it in Python matches the proposal's security posture and the original guard-list intent.
**Alternatives**: Guard logic in QML delegates (rejected — security rule must not be skin-deep); guard in both layers (rejected — single source of truth in Python, QML purely declarative).

### D4: Sorting via a view control, not column headers
**Choice**: A sort dropdown/segmented control at the top of the catalog view (by name / size / guard), implemented as a model `sort()` or QML `SortFilterProxyModel`.
**Rationale**: Cards have no column headers to click. A dedicated sort control is clearer than simulating headers and avoids coupling sort to the delegate.
**Alternatives**: No sorting (regression vs current `setSortingEnabled`), clickable pseudo-headers (cluttered for cards — rejected).

### D5: "Files (advanced)" view stays a compact `ListView`, not cards
**Choice**: The Files tab uses a denser row delegate over a `FileTreeModel`, retaining the protected-path guard in the model.
**Rationale**: The Files view lists hundreds of tree directories; cards would waste space. It is an advanced/power-user view, so it does not need the same polish as the primary catalog. Keeping it a (compact) `ListView` preserves consistency with the new architecture without over-investing.
**Alternatives**: Cards (too sparse for hundreds of rows), keep a `TreeView` (mixing widget styles — rejected for consistency).

### D6: Dev-time filesystem QML, ship-time `qrc` packaging
**Choice**: During development, `QQmlApplicationEngine.load()` reads `.qml` from `systemimgkit/gui/qml/` on disk (fast edit-reload). For distribution, the `.qml` tree is registered in a `.qrc` and compiled so the package ships self-contained.
**Rationale**: Filesystem loading makes iteration fast; `qrc` makes the installed package robust to missing files. Two-stage (dev file → ship qrc) gives both.
**Alternatives**: Always-filesystem (fragile when installed), always-qrc (slows edit-reload — rejected for dev ergonomics).

### D7: `Controller(QObject)` as the QML↔Python bridge
**Choice**: A single `Controller` exposes `Q_INVOKABLE`/`@Slot` methods (openImage, doUnpack, doCatalog, doPack, cancel) and `Q_PROPERTY`/`Signal` for state the QML binds to (imageInfo, isReady, riskOverride, reclaimTotal, warnings list, progress busy). It owns the `Worker` lifecycle. `AppCardModel` and `FileTreeModel` are exposed as context properties.
**Rationale**: One bridge object keeps the QML ↔ Python surface small and auditable; the model objects stay data-only. This mirrors the existing `MainWindow` responsibilities, translated to the QML binding model.

## Risks / Trade-offs

- [Rewrite of a working, near-complete UI] → Mitigation: backend is 100% reused; the migration is confined to `gui/`; `system-img-debloat-tool` is untouched and remains the source of truth for behavior. A failing QML migration cannot regress the CLI or the image pipeline.
- [QAbstractItemModel is more code than QTreeWidget item-pushing] → Mitigation: `AppCardModel` is a flat list (apps are not deeply nested), so a list model (not a full tree model) suffices — far simpler than the original `QTreeWidget` plumbing.
- [Lost native column-header sorting] → Mitigation: D4 sort control; explicitly accept this as an intentional trade-off for the card aesthetic.
- [QML + Python signal/threading pitfalls (touching GUI from worker thread)] → Mitigation: `Worker` already emits signals queued to the main thread; the `Controller` connects to those signals and updates QML-bindable properties on the main thread only — same threading discipline as today.
- [Universal theme availability / rendering on minimal Linux installs] → Mitigation: Controls 2 + Universal ship with PySide6 (already a dependency); no new system package. Verify on the target Qt version during implementation.
- [QML edit-reload vs shipped qrc divergence] → Mitigation: D6 two-stage; a build/packaging step registers the same `.qml` files into `qrc`, so the shipped set is identical to the dev set.

## Migration Plan

1. Add `systemimgkit/gui/qml/` with `main.qml` and delegates; add `AppCardModel`, `FileTreeModel`, and `Controller` to `systemimgkit/gui/`.
2. Rewire `gui/app.py` to construct `QApplication` + `QQmlApplicationEngine`, expose the `Controller` and models as context properties, and load `main.qml` from the filesystem (dev path).
3. Port each existing `MainWindow` behavior onto the `Controller`/models, reusing `Worker` unchanged; keep elevation logic (`try_elevate`, `SIK_ORIG_UID`) in `app.py`.
4. Remove `gui/mainwindow.py` once behavior parity is verified.
5. Add the `.qrc` + packaging step so the installed package loads from compiled resources.
6. Verify parity against the existing spec scenarios (open/unpack/catalog/select/pack, guard resistance, progress/cancel, warnings).

**Rollback**: `gui/mainwindow.py` is deleted only after parity is confirmed. Until then it is retained, and `app.py` can be switched back to the QtWidgets entry by reverting the engine-construction branch — the backend is unaffected either way.

## Post-Implementation Decisions (shared_blocks + SELinux + root helper)

### D8: Normal-user GUI with per-operation root helper (vs whole-process elevation)
**Choice**: GUI runs as a normal user; unpack/pack run via `root_helper.py` subprocess (pkexec). 
**Rationale**: Root-process native GTK file dialogs cannot reach the user's home. Per-operation pkexec (one prompt per unpack/pack) is the right trade-off: native dialogs work, SELinux/setxattr run in the root helper, CLI is unaffected.
**Alternatives rejected**: Whole-process pkexec (breaks native file dialogs); non-native Qt dialog + DontUseNativeDialog (mis-handles long dir names).

### D9: shared_blocks rebuild via Android e2fsdroid (vs standard mke2fs -d)
**Choice**: Compile Android `mke2fs` + `e2fsdroid` from `LonelyFool/e2fsdroid_and_mke2fs` (static-linked, bundled at `ext4tools/linux-x86_64/`). `e2fsdroid -e -s -f staging -a / -C fs_config -S file_contexts image`.
**Rationale**: Standard e2fsprogs 1.45.5 lacks shared_blocks support; `mke2fs -d` expands dedup'd blocks → image inflates beyond partition. Android e2fsdroid with `-s` (SHARE_DUP) reproduces block-level dedup.
**Pitfall**: `-e` (unix io) is required; without it e2fsdroid uses sparse-io on a non-sparse file → error 234.

### D10: SELinux via e2fsdroid -S/-C (not mount-based restore)
**Choice**: Generate `file_contexts` (two-column: regex_path + context) and `canned fs_config` (path uid gid mode [capabilities=N]) from the manifest; pass to e2fsdroid via `-S`/`-C`. Skip `_restore_metadata` for shared_blocks images.
**Rationale**: shared_blocks images refuse rw mounts → mount-based `_restore_metadata` fails silently → no SELinux → bootloop. e2fsdroid sets xattrs during population (no mount needed).
**Pitfalls**: file_contexts must include root `/` and `/lost\+found` rules; paths must be `re.escape`d; e2fsdroid does NOT copy security.selinux xattrs from staging (even with xattrs present).

### D11: symlink SELinux capture with follow_symlinks=False
**Choice**: `os.getxattr(path, name, follow_symlinks=False)` for all file types including symlinks.
**Rationale**: `/init` is a symlink with `u:object_r:init_exec:s0`; default `follow_symlinks=True` follows to target (may not exist) → None. Removing the `ftype != "symlink"` exclusion in `_add_entry` ensures all files get their SELinux context captured.

### D12: Target partition size (smaller image for dynamic super)
**Choice**: `pack.pack(target_blocks=N)` builds at N blocks instead of the original block count; GUI "探测设备分区" button probes `fastboot getvar partition-size:system_a`.
**Rationale**: Device super partition's system_a (e.g. 7.68 GB) is smaller than the original image (11.4 GB); must build a smaller image to fit. Tool never enlarges (rejects target > original).

### D13: _du inode-dedup for hardlink-aware size
**Choice**: `pack._du()` deduplicates by (device, inode) before summing st_size.
**Rationale**: Android system trees use hardlinks; per-path st_size double-counts shared data, making staging appear larger than the partition.
