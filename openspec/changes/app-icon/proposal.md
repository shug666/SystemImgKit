## Why

SystemImgKit currently has **no application icon**. `gui/app.py` sets only `setApplicationName("SystemImgKit")`; there is no `setWindowIcon`, no `.desktop` entry, no SVG/PNG assets, and `qml.qrc` registers only `main.qml`. On Linux the window shows the generic Qt/blank icon in the taskbar, title bar, and app launcher, and the app cannot be pinned or found by icon in a menu. As a polished QML "instrument panel" UI (see `gui-qml-migration`), the tool now reads as professional in-app but anonymous at the OS shell level. Adding a coherent icon set closes that gap.

## What Changes

- Introduce an **application icon** for SystemImgKit based on a "layered system image" metaphor: a stack of three layers tinted with the existing guard colors (core = red, guarded = amber, ok = green), conveying both "ext4 system image" (the literal artifact) and "trim a layer" (the debloat action).
- Ship a **vector master** (`icon.svg`) plus **rasterized PNGs** at standard sizes (16, 22, 24, 32, 48, 64, 128, 256 px) so the icon is crisp in the QML title bar (small) and legible in the Linux taskbar/dock/menus (large).
- Register the icon in `qml.qrc` (added `<qresource prefix="/">` with `icon.svg` and the PNGs) and rebuild `qml_rc.py` so the icon is available from the Qt resource system in both dev and installed modes.
- Call `app.setWindowIcon(QIcon(":/icon.svg"))` in `gui/app.py` so the running window carries the icon.
- Add a **`.desktop` entry** and a **hicolor icon-theme** install set (`data/systemimgkit.desktop`, `data/icons/hicolor/<size>/apps/systemimgkit.png`) plus the install step that copies them into `$XDG_DATA_DIRS` / `~/.local/share`, so the app appears in application menus and the launcher by icon.
- Include the new assets in `pyproject.toml` `[tool.setuptools.package-data]`.

## Capabilities

### New Capabilities
<!-- None — no new capability. -->

### Modified Capabilities
- `gui`: the application window and OS launcher entry SHALL carry a coherent application icon (window icon via `setWindowIcon`, plus a `.desktop` entry + hicolor theme for shell integration). The icon SHALL be a layered-stack motif tinted with the guard palette so the visual identity is consistent with the in-app guard semantics. No operational behavior changes.

## Impact

- **Code**: `systemimgkit/gui/app.py` gains a `setWindowIcon` call; `systemimgkit/gui/qml.qrc` gains an icon `<qresource>`; `qml_rc.py` is regenerated; new asset tree under `systemimgkit/gui/resources/` (SVG + PNGs); new install-data tree under `systemimgkit/data/` (`.desktop` + hicolor PNGs); `pyproject.toml` `package-data` extended.
- **Dependencies**: none added — PySide6 ships the SVG image plugin and `QIcon` SVG support; rasterization uses an offline tool (e.g. `rsvg-convert`/`inkscape`) committed PNGs are checked in, so no runtime image tool is required.
- **Reused as-is**: all backend (`unpack`/`catalog`/`pack`/`avb`), the Controller/Worker/QML architecture, and the dev-vs-qrc loading branch in `app.py`. The icon load follows the same filesystem-vs-qrc pattern already in `app.py`.
- **Security posture unchanged**: the icon is a static visual asset with no logic; no new permissions, no privilege changes, no network.
- **Out of scope**: no CLI icon, no macOS `.icns`/Windows `.ico` bundling, no in-app branding/wordmark beyond the window icon, no change to the QML layout or guard semantics. Linux (the project's platform, per `pyproject.toml` `requires-python`/ext4tools `linux-x86_64`) is the target; cross-platform icon packaging is a later concern.
