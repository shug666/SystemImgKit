## MODIFIED Requirements

### Requirement: Catalog view with checkboxes and guard indicators
The catalog SHALL be rendered as a **card-style `ListView`** (one card per app directory) using QtQuick.Controls 2, with a checkbox, app name, partition, privilege, recursive size, and file-count on each card. Guard level SHALL be expressed via a color/badge on the card (core = locked-red, guarded = amber, deletable = default) rather than a text column; the badge SHALL keep its semi-transparent tinted background and gain consistent internal padding. Sorting SHALL be offered via a control in the view (by name, size, or guard level) rather than a clickable column header. The card list SHALL be driven by a `QAbstractItemModel` (`AppCardModel`); the view only renders model data and forwards user selection intent. Selecting a deletable app adds it to the deletion set; guarded/core cards resist selection with the guard reason shown as a **styled tooltip** (token background + hairline border) or badge. The empty state of the catalog list SHALL render as a centered icon + title + subtitle, not a single text line.

#### Scenario: Select a deletable app
- **WHEN** the user checks `YouTube` under `/product/app`
- **THEN** the entry is added to the deletion set and the total reclaimed size updates

#### Scenario: Guarded entry resists selection
- **WHEN** the user attempts to check `GmsCore`
- **THEN** the checkbox does not activate and the card shows the guard reason as a styled tooltip/badge

#### Scenario: Sort the catalog
- **WHEN** the user picks "size" in the sort control
- **THEN** the card list reorders by descending recursive size without re-querying the catalog

#### Scenario: Empty catalog shows a modern empty state
- **WHEN** a directory section has no apps
- **THEN** the catalog list shows a centered icon, a title, and a subtitle rather than a single text string

### Requirement: Big-file view
The system SHALL provide a "大文件" (big files) view that lists the largest files across the extracted tree (capped at ~300 entries, sorted by size descending), with path, size, and a guard indicator. The separate "文件" (full-tree) view SHALL be removed; the view tabs are "应用" and "大文件" only. Each big file SHALL carry a guard level ("none"|"guarded"|"core") computed as: system-protected paths (e.g. /apex, /system_dlkm) → "core" (hard-locked, never deletable); otherwise the guard level of the app the file belongs to (by image_path prefix); files under no app → "none". Selection rules mirror the app catalog exactly: core never selectable, guarded selectable only with risk-override on — so the big-file view cannot bypass the "允许删除受保护应用" toggle. Files under a selected app directory SHALL automatically appear checked (deleted with the app). The reclaimable total SHALL include both app deletions and manually-checked big-file deletions. Its empty state SHALL render as a centered icon + title + subtitle.

#### Scenario: Big files listed by size
- **WHEN** the catalog is loaded
- **THEN** the big-file view shows the 300 largest files by size descending

#### Scenario: App selection syncs to big files
- **WHEN** the user selects an app in the catalog view
- **THEN** big files under that app's directory show as checked in the big-file view (deleted with the app)

#### Scenario: Big-file view empty state
- **WHEN** the big-file view has no loaded files
- **THEN** it shows a centered icon + title + subtitle rather than a single text string

#### Scenario: Guarded big file respects the risk-override toggle
- **WHEN** a big file belongs to a guarded app and risk-override is off
- **THEN** the file's checkbox is disabled and cannot be checked; turning risk-override on makes it selectable

#### Scenario: Core / system-protected big files are never deletable
- **WHEN** a big file is under a core app or a system-protected path (e.g. /apex)
- **THEN** its checkbox is disabled regardless of the risk-override toggle

#### Scenario: Turning risk-override off drops guarded big-file selections
- **WHEN** risk-override is turned off while guarded big files are checked
- **THEN** those guarded selections are cleared (non-guarded selections are kept)

#### Scenario: The "文件" full-tree view is removed
- **WHEN** the view tabs render
- **THEN** only "应用" and "大文件" are offered; there is no full-tree Files view

### Requirement: Modern card-style catalog presentation
The catalog `ListView` SHALL use the QtQuick.Controls 2 **Universal** theme as its visual base, with cards showing hover and selection states, readable spacing, and a monospace rendering of size/counts. The presentation layer SHALL be authored in QML (`.qml` files) loaded via a `QQmlApplicationEngine`, separating view from logic.

#### Scenario: Card hover and selection feedback
- **WHEN** the user hovers over a deletable card
- **THEN** the card shows a hover highlight, and checking it shows a distinct selected state

#### Scenario: Image-open panel reflects image metadata
- **WHEN** the user opens a `system.img`
- **THEN** the QML image panel shows the image name, size, detected format, and AVB-footer presence, and unpacking starts automatically (no separate Unpack action to enable) — see "Unpack on image pick"

## ADDED Requirements

### Requirement: Embedded SVG icon system
The GUI SHALL ship a set of 24×24 stroke-style SVG icons bundled via an `/icons` qresource prefix in `qml.qrc` (at minimum: open, unpack, list, pack, cancel, probe, sort, files, bigfile, risk). Icons SHALL be rendered via `Image` loaded from the qrc and recolored at runtime (e.g. via `ColorOverlay`) against the existing token palette, so a single SVG serves normal/active/disabled states. Every primary action button (open image, unpack, catalog, pack, cancel, probe device partition) SHALL display a leading icon. The icon set SHALL be rebuilt through the existing `_rasterize.py` / `pyside6-rcc` pipeline so `qml_rc.py` stays in sync.

#### Scenario: Action buttons show icons
- **WHEN** the GUI renders the rail
- **THEN** the open-image, unpack, catalog, pack, cancel, and probe buttons each show a leading icon tinted to the token palette

#### Scenario: Icons recolor with state
- **WHEN** a button is disabled or active
- **THEN** its icon recolors (disabled → faint, active → accent) without a separate SVG asset

### Requirement: Button hierarchy
The GUI SHALL use three reusable button styles — `PrimaryButton` (accent fill, white text, for the action of consequence: pack), `SecondaryButton` (outline, for open-image / probe), and `GhostButton` (borderless, for cancel) — replacing uniform flat buttons. All buttons SHALL share `radius: 6`, a 32 px minimum height, and a hover/press response (PrimaryButton darkens on hover and scales to 0.98 on press). The choice of style SHALL communicate importance without changing any `enabled` binding or `onClicked` behavior.

#### Scenario: Pack is visually primary
- **WHEN** the rail renders
- **THEN** the "打包" button is the only accent-filled (Primary) button, visually distinct from open/probe (Secondary) and cancel (Ghost)

#### Scenario: Button bindings preserved
- **WHEN** any styled button is clicked
- **THEN** it invokes the same slot as before the restyle (e.g. pack → `Controller.packDefault()`, cancel → `Controller.cancelWorker()`), and respects the same `enabled` state

### Requirement: Application header bar
The GUI SHALL render a top header bar spanning the window width (≈48 px) containing the application logo (from the qrc) and "SystemImgKit" wordmark on the left, and the risk-status indicator dot plus the "可回收 \<total\>" reclaim badge on the right. The corner wordmark SHALL be removed from the left rail; rail content SHALL begin at the image-info group. The reclaim badge and risk dot SHALL be sourced from the existing `riskOverride` and `reclaimTotal` properties (moved up from the log-dock status row), not computed anew.

#### Scenario: Header shows reclaim and risk state
- **WHEN** the GUI is running
- **THEN** the header right side shows a risk dot (warn when override is on, ok otherwise) and the current reclaimable total

#### Scenario: Rail no longer carries the corner wordmark
- **WHEN** the rail renders
- **THEN** it begins with the image-info group, with the wordmark present only in the header

### Requirement: Stateful pipeline stepper
The catalog → pack pipeline SHALL be presented as a 2-step stepper (列出应用 / 打包), one row per step: a 22 px circle containing an icon or check + a label, the active row clickable, NOT as numbered `1/2/3` entries with a play glyph. Unpack is no longer a stepper step — it is triggered automatically when an image is picked (see "Unpack on image pick"). Step state SHALL be **derived** from the existing readiness flags (`canCatalog` / `canPack`): a step is `done` (ok-colored filled check) once a later step has become available, `active` (accent outline with the step icon) when it is the next runnable step, and `pending` (dim outline, not clickable) otherwise. Clicking the active step SHALL run `Controller.doCatalog()` (列出) or `Controller.packDefault()` (打包); pending steps SHALL not be clickable. The standalone run buttons and play glyphs SHALL be removed. Note: unpack success already auto-triggers `doCatalog`, so "列出" usually resolves on its own; it remains clickable to re-list.

#### Scenario: Step state reflects readiness
- **WHEN** catalog has loaded and pack is available (`canPack` true)
- **THEN** step 1 (列出应用) shows as done, and step 2 (打包) shows as active/clickable

#### Scenario: Clicking the active step runs it
- **WHEN** the user clicks the active 列出应用 step
- **THEN** `Controller.doCatalog()` runs, identical to the prior run button

### Requirement: Unpack on image pick
Picking an image SHALL start unpacking automatically, using the image's own directory as the workspace — there is no separate "解包" button and no workspace folder dialog. The Controller SHALL expose `openImageAndUnpack(path)` (open the image, then `doUnpack(dirname(image))` if the image is valid and the GUI is idle), `currentOp` (the in-flight operation kind: "" / "unpack" / "catalog" / "pack" / "probe"), and `unpacked` (true once an unpack completed successfully, reset when a new image is opened). The image card SHALL report the unpack stage: a pulsing spinner + "解包中…" while `currentOp === "unpack"`, and a green check + "已解包" once `unpacked`. If the image is invalid or the GUI is busy, picking SHALL NOT start an unpack.

#### Scenario: Picking a valid image auto-unpacks into the image directory
- **WHEN** the user picks a valid `system.img`
- **THEN** the image is opened and unpacking starts immediately with the image's directory as the workspace, and the image card shows "解包中…"

#### Scenario: Picking an invalid image does not unpack
- **WHEN** the user picks an unsupported or unreadable file
- **THEN** the image-open error is shown and no unpack is started (`currentOp` stays "")

#### Scenario: Unpack success is reflected in the image card
- **WHEN** the automatic unpack completes successfully
- **THEN** the image card shows the "已解包" badge and (per existing behavior) cataloging is auto-triggered

### Requirement: Normalized spacing, rounding, and log-dock polish
The left rail SHALL separate its groups (镜像 / 流程 / 风险 / 视图) with 24 px inter-group spacing and a `fsMicro` letter-spaced subtitle, using at most one hairline per gap. All controls SHALL share `radius: 6`. The log dock SHALL show a terminal-style glyph in its title row and render the most recent log line in primary text with prior lines dimmed (a "live tail"), preserving the existing auto-scroll and horizontal-scroll behavior.

#### Scenario: Rail groups are visually separated
- **WHEN** the rail renders
- **THEN** each group is preceded by a letter-spaced subtitle and 24 px of spacing, with no dense double hairlines

#### Scenario: Log dock emphasizes the latest line
- **WHEN** new log lines arrive
- **THEN** the most recent line is primary-colored and older lines are dim, and the view auto-scrolls to the bottom unchanged

### Requirement: Themed function-area cards
Each left-rail function area (镜像 / 流程 / 风险 / 视图) SHALL be rendered as a distinct **card**: the brightest raised surface (`c.card`) with a hairline border and `radius: 8`, carrying (a) a theme-colored 3 px left rail and (b) a header row of a theme-tinted rounded icon badge plus the section title. Each area SHALL have a stable identity theme color — 镜像 = blue, 流程 = violet, 风险 = amber, 视图 = teal — distinct from the guard semantic colors. Cards SHALL be separated by the rail's inter-card spacing (no hairline dividers between them). Card-ification is purely visual: it SHALL NOT alter the bindings, slots, or behavior of any contained control (stepper state, override toggle, target-size field, probe button, tab bar).

#### Scenario: Each rail area is a visible card with a theme color
- **WHEN** the rail renders
- **THEN** the 镜像 / 流程 / 风险 / 视图 areas each appear as a bordered rounded card with a theme-colored left rail and a theme-tinted icon+title header, and the four theme colors are visually distinct

#### Scenario: Card-ification preserves control behavior
- **WHEN** the user toggles the risk override, edits the target size, or switches the view tab inside their cards
- **THEN** the behavior is identical to before card-ification (override confirmation, target-block write-back, stack switching)

### Requirement: Bounded log streaming under high-frequency progress
The log dock SHALL remain responsive while a worker streams high-frequency progress (e.g. rsync `--info=progress2`, which rewrites a single status line with `\r` dozens of times per second). The Controller SHALL (a) treat a `\r`-carrying progress line as an in-place update of the previous log line (not an append), so a long rsync run adds one rolling line rather than thousands; (b) coalesce `warningsChanged` notifications to at most one per ~100 ms so the QML RichText log re-renders at a bounded rate, not once per progress line; and (c) cap the retained log at a fixed maximum line count (older lines dropped). The log SHALL still show the final progress value and all non-progress lines.

#### Scenario: rsync progress does not flood the log
- **WHEN** an unpack streams 500+ rsync progress lines
- **THEN** the log retains a single rolling progress line (the latest value) plus the surrounding non-progress lines, and the UI stays responsive

#### Scenario: Non-progress lines are preserved
- **WHEN** progress lines are interspersed with real log lines (e.g. "捕获元数据清单…")
- **THEN** the real log lines remain in the log and are not collapsed into the progress line

### Requirement: Application icon
The application icon SHALL be a single vector SVG (`icon.svg`, 128×128 viewBox) composed of a brand-blue (#2A6CF6, matching the in-app accent) rounded-square tile with a centered white `package-minus` glyph sourced from the Lucide icon library (ISC license, free for commercial use). The glyph — a parcel box with a minus sign — expresses "system package minus contents / debloat". Rasterized PNGs at 16/22/24/32/48/64/128/256 px SHALL be regenerated from the SVG via the existing `_rasterize.py` pipeline, which SHALL write BOTH the qrc-facing set (`gui/resources/icon-<px>.png`) AND the hicolor set (`data/icons/hicolor/<px>x<px>/apps/systemimgkit.png` used by `install-icons` / the `.desktop` entry), so the window icon (`QIcon(":/icon.svg")`) and the launcher/menu icon stay in sync after a redraw.

#### Scenario: Window icon uses the new SVG
- **WHEN** the GUI launches
- **THEN** the window icon is loaded from `:/icon.svg` and is non-null

#### Scenario: Icon legible at small sizes
- **WHEN** the icon is rasterized to 16 px
- **THEN** the blue tile and the white package-minus glyph silhouette remain recognizable

#### Scenario: Launcher icon stays in sync with a redraw
- **WHEN** `icon.svg` is redrawn and `_rasterize.py` is run
- **THEN** both `gui/resources/icon-<px>.png` and `data/icons/hicolor/<px>x<px>/apps/systemimgkit.png` are regenerated from the new SVG (no stale hicolor set)

## REMOVED Requirements

### Requirement: Files (advanced) view
The full-tree "文件" (Files advanced) view is removed. Arbitrary-file deletion across the whole tree is no longer exposed in the GUI; users delete apps (via the 应用 view) and large files (via the 大文件 view, with the same guard/risk-override rules). The `FileTreeModel`/`fileModel` and its delegate are no longer wired to any view.

