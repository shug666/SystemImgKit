## Why

The GUI presentation layer is already QML (`main.qml`, ~856 lines) and carries a
working design-token system, but it reads as **dated and cramped** for a modern
desktop tool:

- **Zero icons.** Every action (`打开镜像… / 解包 / 列出应用 / 打包 / 取消 / 探测设备分区`)
  is a bare text button or a `►` glyph — no pictographic affordances.
- **No button hierarchy.** All buttons are `flat: true`, so the critical
  "打包" action is visually identical to "取消".
- **The pipeline is faked with `1 ► / 2 ► / 3 ►`** — numbers plus a play glyph
  with no done/active/pending state, so the user cannot see how far they are.
- **The left rail is overstuffed.** 248 px holds image info + pipeline + risk
  switch + target size + view tabs with no breathing room, and the
  `SYSTEMIMGKIT` wordmark is cramped into the corner instead of a real header.
- **Empty states and badges are hand-rolled `Text` strings**, not the
  icon+title+subtitle pattern a modern desktop app uses.

The backend (`Controller` + `AppCardModel` + workers + root helper) is correct
and decoupled. This change is **purely the visual layer**: icons, button
hierarchy, a real header, a stepper pipeline, spacing, and empty-state polish.
No Python API, no data flow, no operational behavior changes.

## What Changes

- **Icon system.** Add a `/icons` qresource prefix to `qml.qrc` with ~10
  24×24 stroke-style SVGs (open / unpack / list / pack / cancel / probe / sort
  / files / bigfile / risk), rendered via `Image` + `ColorOverlay` so they
  recolor with the token palette. Reuse the existing `_rasterize.py` /
  `pyside6-rcc` pipeline. Every primary action button gets an icon.
- **Button hierarchy.** Introduce three reusable styled buttons —
  `PrimaryButton` (accent fill, white text, the action of consequence),
  `SecondaryButton` (outline), `GhostButton` (borderless) — replacing every
  `flat: true` button. The stepper step-clicks and the target-size/probe
  buttons keep their existing `enabled`/`onClicked` bindings.
- **Header.** Add a 48 px top header spanning the window: qrc app logo +
  "SystemImgKit" on the left; risk-status dot + "可回收 <reclaimTotal>" badge
  on the right. The rail's corner wordmark is removed; rail content starts at
  the "镜像" group.
- **Stepper pipeline.** Replace the `1/2/3 + ►` block with a 3-step stepper:
  22 px circle (icon or check) + label, full-row clickable. Step state is
  *derived* from `Controller.canUnpack / canCatalog / canPack`
  (done → `c.ok` filled check, active → `c.accent` outline, pending → `c.line`
  dim). The `►` glyph and the separate run buttons are removed; clicking the
  active step runs the same slot (`wsDialog.open / doCatalog / packDefault`).
- **Spacing & rounding.** Rail groups get 24 px inter-group spacing and
  `fsMicro`+letterSpacing subtitles instead of dense hairlines; all controls
  share `radius: 6`; buttons have a 32 px minimum height.
- **Empty-state & polish.** The three `ListView` empty states become
  centered icon + title + subtitle. The log dock gets a terminal glyph and a
  current-line highlight. Tooltips become styled (token bg + line border).
- **Hard constraint**: only `main.qml` and `qml.qrc` change (+ new SVG files
  under `gui/resources/icons/`). The token system `c` and font sizes are
  *extended*, not replaced. All Chinese labels and the native
  `FileDialog`/`FolderDialog`/`MessageDialog` are preserved. No `Controller`
  / `models.py` / `app.py` API change.

## Capabilities

### New Capabilities
<!-- None — no new capability. -->

### Modified Capabilities
- `gui`: the QML presentation layer gains a real header, an embedded SVG icon
  system, button hierarchy, a stateful stepper pipeline, normalized spacing,
  and modernized empty states — while preserving all operational requirements
  (open/unpack/catalog/select/pack, guard protection, probe, target size,
  normal-user + per-operation root, the three list views). Spec deltas describe
  the icon system, button hierarchy, header, stepper, and empty states; the
  existing guard / model / view requirements are MODIFIED only in their visual
  clauses (icons + badges + hierarchy), not in behavior.

## Impact

- **Code**: `systemimgkit/gui/qml/main.qml` rewritten in place (view layer
  only). `systemimgkit/gui/qml.qrc` gains an `/icons` prefix. New SVG assets
  under `systemimgkit/gui/resources/icons/`. `qml_rc.py` regenerated via
  `pyside6-rcc`.
- **No Python change**: `Controller`, `AppCardModel`, `FileTreeModel`,
  `BigFileModel`, `app.py`, `rootops.py`, `workers.py` untouched. The QML
  binds to the same Properties/Signals (`imageName / imageOk / canUnpack /
  canCatalog / canPack / progressBusy / riskOverride / reclaimTotal /
  sections / appModel / fileModel / bigFileModel / targetSizeGB / warnings …`)
  and calls the same Slots.
- **Dependencies**: none added — `ColorOverlay` ships with QtQuick
  (`import QtQuick`), SVG via `Image` is built in.
- **Security posture unchanged**: guard protection stays in the Python model
  layer; QML still never authorizes a deletion. The visual guard indicators
  (color/badge) are presentation of model state, not enforcement.
- **Non-goals**: no dark mode toggle, no re-theme beyond the existing light
  tokens, no new views or capabilities, no CLI change, no packaging change
  beyond the qrc/icons.
