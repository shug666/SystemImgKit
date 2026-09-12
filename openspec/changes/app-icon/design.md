## Context

SystemImgKit runs on Linux (ext4tools are `linux-x86_64`, `pyproject.toml` targets Python ≥3.12 + PySide6). Its GUI is a QML "instrument panel" (`main.qml`) loaded via `QQmlApplicationEngine` with a dev/filesystem vs installed/`qrc` branch in `gui/app.py`. The UI defines a token palette in `main.qml`, including a guard triad — `ok #1F9D55` (deletable), `warn #C8821A` (guarded), `danger #D43A3A` (core) — which is the single loudest semantic in the app. Today there is no icon anywhere: no `setWindowIcon`, no `.desktop`, no hicolor, no assets.

## Goals / Non-Goals

**Goals**
- A single coherent icon motif recognizable at 16 px (title bar) through 256 px (dock/menu).
- The motif ties to the app's identity: a system image being trimmed, using the guard palette so the icon and the in-app guard semantics read as one system.
- Window icon works in both dev and installed (qrc) modes.
- Shell integration on Linux: `.desktop` entry + hicolor theme so the app is launchable/menu-visible by icon.

**Non-Goals**
- macOS `.icns` / Windows `.ico` (not the target platform).
- A full wordmark or in-app branding screen.
- Animated icons.
- Re-theming the QML palette; the icon reuses existing tokens, it does not redefine them.

## Decisions

### Decision 1 — Motif: layered stack tinted with the guard palette

The icon is a **stack of three horizontal layers** (an ext4 system image as a stacked block), each tinted with one guard color:

```
  ┌──────────────┐
  │ ■■■■■■■■■■■■ │  core     #D43A3A  (red — locked, brick-risk)
  ├──────────────┤
  │ ■■■■■■■■■■■■ │  guarded  #C8821A  (amber — protected)
  ├──────────────┤
  │ ■■■■■■■■■■■■ │  ok       #1F9D55  (green — deletable)
  └──────────────┘
   SystemImgKit
```

**Rationale**: A stacked block reads as "system image / partition layers" (the literal artifact) at a glance. The three guard colors are the app's unique semantic — not a generic shield/scissors — and the form "stack with a removable layer" implies the trim/debloat action. A shield was considered (Direction B) but is over-used by security tools and does not convey the image/trim action; a scissors (Direction A) is generic and collides with file managers. The layered stack is specific to SystemImgKit and legible at small sizes (horizontal bands survive 16 px rasterization better than fine internal detail).

**Alternatives rejected**: B (tri-color shield) — legible but generic; A (scissors + block) — generic action icon, collides with file managers.

### Decision 2 — Vector master + committed raster PNGs

`resources/icon.svg` is the source of truth. Raster PNGs at 16/22/24/32/48/64/128/256 px are generated once (offline, e.g. `rsvg-convert` or `inkscape`) and **committed to the repo**, not generated at build/install time. This avoids a runtime/build dependency on an SVG rasterizer and keeps installs reproducible.

**Rationale**: PySide6 ships the SVG image plugin, so `QIcon(":/icon.svg")` works for the window icon; but Linux taskbars/docks and the `.desktop`/hicolor system prefer pre-rasterized PNGs at named sizes for crispness and theme integration. Committing the PNGs removes a build-time tool dependency.

### Decision 3 — Register via `qml.qrc`, not a separate `.qrc`

Add a new `<qresource prefix="/">` to the existing `qml.qrc` containing `resources/icon.svg` (alias `icon.svg`) and the PNGs (e.g. `resources/icon-256.png` alias `icon-256.png`). Regenerate `qml_rc.py` with `pyside6-rcc`. The window icon is loaded as `QIcon(":/icon.svg")` in `app.py`, alongside the existing dev-vs-qrc branch (filesystem in dev, `qrc:` in installed).

**Rationale**: one resource file, one `qml_rc.py`, matching the existing packaging pattern (`pyproject.toml` already lists `gui/*.qrc` and `gui/qml_rc.py`). No new build step beyond the already-used `pyside6-rcc`.

### Decision 4 — Linux shell integration via `.desktop` + hicolor

Ship `data/systemimgkit.desktop` (Type=Application, Name, Comment, Exec=`systemimgkit`, Icon=`systemimgkit`, Terminal=false) and `data/icons/hicolor/{16x16,22x22,24x24,32x32,48x48,64x64,128x128,256x256}/apps/systemimgkit.png`. An install step copies these to `~/.local/share` (or `--prefix`-style `datadir`) so the launcher/menu shows SystemImgKit by icon. The `Icon=systemimgkit` name matches the hicolor basename, so no separate theme file is needed — the hicolor fallback theme resolves it.

**Rationale**: standard, minimal Linux integration. User-scope install (`~/.local/share`) avoids needing root and matches a pip-installed tool; a system install path is left to packagers.

### Decision 5 — Single-color badge variant for light taskbars

The layered icon uses the colored bands on a neutral container. To stay legible on both dark UI chrome (where the app runs) and light Linux taskbars (where the dock lives), the SVG uses the colored bands for the content but keeps the container/keyline high-contrast (dark keyline on light fill, or inverted). A fully monochrome variant is **not** needed because the guard colors are the point; the bands are saturated enough to read on light and dark backgrounds.

**Rationale**: avoids a separate "dark-mode icon" file while keeping the guard palette visible.

## Risks / Trade-offs

- **16 px legibility**: three bands at 16 px can blur. Mitigation: the SVG is designed so each band is ≥1px tall at 16 px, and the 16 px raster is hand-checked (and regenerated from the master, not auto-scaled blindly).
- **SVG plugin at runtime**: rare Qt builds may lack the SVG image plugin. Mitigation: the window icon also has the PNG fallback in the resource, and `setWindowIcon` can take a `QIcon` built from the largest PNG if SVG fails — handled with a try/except fallback to `:/icon-256.png`.
- **Install path ambiguity**: `.desktop` `Exec=systemimgkit` requires the console script to be on `PATH`. If installed in a venv not on `PATH`, the menu entry won't launch. Mitigation: document this; the window icon (always present) is the guaranteed path, `.desktop` is best-effort shell integration.
- **No cross-platform bundle**: acceptable for a Linux-targeted tool; revisit if macOS/Windows targets are added.

## Migration

No data or API migration. The change is purely additive (new assets + one `setWindowIcon` line + qrc/`qml_rc.py` regen + `.desktop`/hicolor + `package-data`). Existing installs keep working; the icon simply appears where it was previously blank.
