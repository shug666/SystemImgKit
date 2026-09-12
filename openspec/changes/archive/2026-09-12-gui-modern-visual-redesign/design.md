# Design — GUI Modern Visual Redesign

## Context & constraints

The view layer is a single QML file, `systemimgkit/gui/qml/main.qml` (~856
lines), rendered by `QQmlApplicationEngine`. It already has a healthy
foundation this change builds on rather than discards:

- A token system `c` (12 colors) and three font sizes (`fsBase 13` / `fsSmall
  11` / `fsMicro 10`) plus spacing tokens (`sp 6`, `pad 12`, `railW 248`).
- Guard semantics encoded as color: `core → c.danger`, `guarded → c.warn`,
  `none → c.ok`.
- A model-driven architecture: `appModel` / `fileModel` / `bigFileModel`
  (`QAbstractItemModel`) + `Controller` (`QObject` Properties/Signals). The
  view only renders and forwards intent.

**Hard rule this design enforces**: the Python API is frozen. Every visual is
sourced from existing bindings:

| Visual need | Bound to |
|---|---|
| Step "done/active/pending" | `canPack`, `canCatalog`, `canUnpack` |
| Risk state dot | `riskOverride` |
| Reclaim badge | `reclaimTotal` |
| Image panel | `imageName`, `imageOk`, `imageSize`, `imageFmt`, `imageAvb` |
| Step run actions | `wsDialog.open()`, `Controller.doCatalog()`, `Controller.packDefault()` |
| Busy / cancel | `progressBusy`, `Controller.cancelWorker()` |

Nothing new is computed in Python; step state is *derived in QML* from the
readiness flags.

## Decision 1 — Icons: embedded SVG in the qrc (Option A)

Rejected alternatives:
- **Qt freedesktop theme icons** (`icon.name`) — zero asset work, but
  appearance varies across desktop environments (GNOME vs KDE vs minimal WMs)
  and breaks the deliberate console/monospace aesthetic.
- **Icon font (Material Symbols subset)** — most "modern," scales crisply,
  colors with text — but requires shipping a TTF and a glyph-code map; heavier
  than this single-view app warrants.

**Chosen**: an `/icons` qresource prefix in the existing `qml.qrc` holding ~10
24×24 stroke-style SVGs. `Image { source: "qrc:/icons/open.svg" }` + a
`ColorOverlay` tinted by a token color. This reuses the established
`_rasterize.py` + `pyside6-rcc` pipeline (already documented in the README),
keeps assets on-brand, and recolors at runtime so one SVG serves multiple
states (active/normal/disabled).

### Icon set (10)
`open` · `unpack` · `list` · `pack` · `cancel` · `probe` · `sort` · `files` ·
`bigfile` · `risk`. Stroke style (1.5 px), `currentColor`-like via
`ColorOverlay`, 24×24 viewBox.

### Helper
A QML function `icon(name, color, size)` returning an `Item` (an `Image`
recolored by `MultiEffect`), so call sites are one line:
`icon("pack", c.accent, 16)`.

### Note — ColorOverlay is unavailable in this Qt (resolved)
The design originally specified `ColorOverlay`. Verification on the target
(PySide6 6.9.3 / Qt 6.9) showed `ColorOverlay` is **not a type** under
`import QtQuick`, `Qt5Compat.GraphicalEffects` is not installed, and
`QtQuick.Effects` ships `MultiEffect` (not `ColorOverlay`). The fallback
documented under Risks was therefore taken: icons are recolored with
`MultiEffect` from `import QtQuick.Effects`, using
`colorization: 1.0` + `colorizationColor: <token>` (the `tint*` properties
do not exist on `QQuickMultiEffect`; the colorization family is the correct
API). `qml_rc.py` was regenerated. No Python change.

## Decision 2 — Button hierarchy (three styles)

Replace every `flat: true` button with one of three reusable components defined
inline in `main.qml` (no new files — QML inline components or `Component` + loader):

| Style | Use | Visual |
|---|---|---|
| `PrimaryButton` | "打包" (the action of consequence) | `c.accent` fill, white text, `radius 6`, hover darkens 8%, press scale 0.98, leading icon |
| `SecondaryButton` | "打开镜像…", "探测设备分区" | `c.line` outline, `c.fg` text, transparent bg, hover bg `c.panelHi`, leading icon |
| `GhostButton` | "取消" | borderless, `c.fgDim`, hover → `c.fg` |

All preserve the existing `enabled` binding and `onClicked` slot. The minimum
height is 32 px; radius 6 across the app.

## Decision 3 — Header

A 48 px `Rectangle` header inserted as the first child of the root
`ColumnLayout`, spanning full width:

```
┌──────────────────────────────────────────────────────────────────┐
│ [logo] SystemImgKit ……………… ◉ risk  [可回收 1.2 GB]              │  48px header
├───────────────┬──────────────────────────────────────────────────┤
│ 镜像           │  apps / files / bigfile                          │
│ 流程 (stepper)│                                                  │
│ 风险           │                                                  │
│ 视图 [tabs]    │                                                  │
└───────────────┴──────────────────────────────────────────────────┘
│ log dock (resizable) …………………………………………………………………… │
```

The rail's corner `SYSTEMIMGKIT` wordmark is **removed** (now lives in the
header). Rail content begins at the "镜像" group. The header right side shows
the risk dot (`riskOverride ? c.warn : c.ok`) and the reclaim badge, moved up
from the log-dock status row (the dock keeps the log, the status moves up).

## Decision 4 — Stepper pipeline

The `1/2/3 + ►` block becomes a 3-row stepper. Each row: a 22 px circle
(contains an icon or a check) + a label, the whole row clickable.

Step state is **derived** (pure function of the readiness flags):

```
canPack  == true  → step3 active, step1 & step2 done
canPack  == false, canCatalog == true → step2 active, step1 done, step3 pending
canPack  == false, canCatalog == false, canUnpack == true → step1 active, step2/3 pending
otherwise (no image) → all pending
```

Circle visuals:
- **done** → `c.ok` filled, white check (`✓`) — or the step icon in white.
- **active** → `c.accent` outline 2 px, step icon in `c.accent`.
- **pending** → `c.line` outline, step icon in `c.fgFaint`, row not clickable.

Clicking the **active** step runs its action (the only clickable row):
`wsDialog.open()`, `doCatalog()`, `packDefault()`. The standalone `►` run
buttons and the numeric labels are removed. "取消" (GhostButton) + indeterminate
`ProgressBar` stay, gated by `progressBusy`.

## Decision 5 — Spacing, rounding, empty states

- Rail groups ("镜像" / "流程" / "风险" / "视图") separated by **24 px** and a
  `fsMicro`+`letterSpacing` subtitle, at most one hairline per gap (remove
  the current dense double-hairlines).
- All controls: `radius: 6`; buttons ≥ 32 px tall; the app-card guard badge
  keeps its existing 0.18-alpha background but gains 1 px internal padding.
- The three empty states (`appList` "该目录无应用", `fileList` "未加载文件",
  `bigFileList` "未加载大文件") upgrade to centered: `icon (c.fgFaint)` +
  `title (fsBase)` + `subtitle (fsMicro)`.
- Log dock: a small terminal glyph in its title row; the **last line** renders
  in `c.fg`, prior lines in `c.fgDim` (visual "live tail"). Auto-scroll
  behavior unchanged.
- Tooltips: styled `ToolTip` (bg `c.bg`, 1 px `c.line` border, `radius 4`).

## Alternatives considered & rejected

- **Re-theme to dark mode** — out of scope; the light tokens are intentional
  (paper-like work surface). A future change can add a theme toggle.
- **Split `main.qml` into multiple files** — tempting at ~900 lines, but adds
  qrc/loader complexity for a single-window tool. Keep one file; rely on the
  inline component pattern for buttons/icon helper.
- **Add icons for every guard badge / sort arrow** — over-ornaments; badges
  stay text ("核心"/"受保护"/"可删") which is clearer than tiny glyphs at
  `fsMicro`.

## Risks

- **`ColorOverlay` import path** — it lives in `QtQuick` (not a separate
  import) in Qt 6. Verify with a smoke launch after P0; fall back to baking
  two SVG variants per icon (normal/disabled) if overlay misbehaves.
- **qrc rebuild step** — `qml_rc.py` must be regenerated (`pyside6-rcc`).
  The README already documents this; tasks call it out so it isn't missed.
- **Stepper state derivation drift** — the derivation assumes `canCatalog`
  implies step1 done. Confirm against `Controller`'s readiness logic (the
  flags re-evaluate on `isReadyChanged`); if `canCatalog` can be true while
  step1 is *not* actually complete, gate on `catalogLoaded` instead. Flagged
  as a verification step in tasks.
- **Single-file size** — the file grows ~150–250 lines (buttons, header,
  stepper, icon helper). Acceptable; inline components keep it readable.

## Open questions

- None blocking. The icon *names* and exact SVG paths are an implementation
  detail chosen at P0; the set (10 icons) is fixed by this design.
