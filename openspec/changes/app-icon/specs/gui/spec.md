## ADDED Requirements

### Requirement: Application window icon
The GUI application window SHALL display an application icon in the window title bar and the host OS taskbar/dock. The icon SHALL be loaded from the Qt resource system (`QIcon(":/icon.svg")`) and applied via `app.setWindowIcon(...)` in `gui/app.py`, working in both the dev (filesystem) and installed (`qrc`) loading branches. If the SVG image plugin is unavailable at runtime, the loader SHALL fall back to a rasterized PNG (`:/icon-256.png`) so the window always carries an icon.

#### Scenario: Window icon shown in dev mode
- **WHEN** the GUI is launched from the source tree (filesystem QML loading)
- **THEN** the window title bar and taskbar show the SystemImgKit icon, not the generic Qt/blank icon

#### Scenario: Window icon shown in installed mode
- **WHEN** the GUI is launched from an installed package (qrc QML loading)
- **THEN** the window title bar and taskbar show the SystemImgKit icon

#### Scenario: SVG plugin unavailable fallback
- **WHEN** the Qt SVG image plugin is not present at runtime
- **THEN** the loader falls back to `:/icon-256.png` and the window still carries an icon

### Requirement: Coherent icon identity (layered stack + guard palette)
The application icon SHALL depict a stacked-block motif (a system image as stacked layers) tinted with the in-app guard palette — core `#D43A3A` (red), guarded `#C8821A` (amber), ok `#1F9D55` (green) — so the shell-level icon identity is consistent with the in-app guard semantics. The icon SHALL be legible at 16 px (title bar) through 256 px (dock/menu), provided as a vector SVG master plus committed raster PNGs at 16/22/24/32/48/64/128/256 px.

#### Scenario: Icon legible at taskbar size
- **WHEN** the icon is rendered at 16 px in the window title bar
- **THEN** the three colored layers remain distinguishable (no band collapses below 1 px)

#### Scenario: Icon legible at dock/menu size
- **WHEN** the icon is rendered at 128–256 px in a dock or application menu
- **THEN** the layered-stack motif and guard colors are clearly readable

### Requirement: Linux shell integration (desktop entry + hicolor theme)
The project SHALL ship a `.desktop` entry (`data/systemimgkit.desktop`, Type=Application, Exec=`systemimgkit`, Icon=`systemimgkit`) and a hicolor icon-theme install set (`data/icons/hicolor/<size>/apps/systemimgkit.png` at the standard sizes) so the application appears in Linux application menus and launchers by icon. The install step SHALL place these into the user data directory (`~/.local/share`) by default, requiring no root privileges.

#### Scenario: App appears in launcher by icon
- **WHEN** the icons are installed (via the `install-icons` command or manual copy) and `systemimgkit` is on `PATH`
- **THEN** the application menu/launcher shows SystemImgKit with the layered-stack icon, and launching it starts the GUI

#### Scenario: User-scope install needs no root
- **WHEN** the user runs the icon install
- **THEN** the `.desktop` and hicolor PNGs are written under `~/.local/share` and no `pkexec`/`sudo` is required

### Requirement: Icon assets packaged for distribution
The icon SVG, raster PNGs, `.desktop` entry, and hicolor PNGs SHALL be included in the packaged distribution via `pyproject.toml` `[tool.setuptools.package-data]`, so a `pip install` ships the full icon set without a separate runtime rasterization step.

#### Scenario: Installed package contains icon assets
- **WHEN** the package is installed via pip
- **THEN** the installed tree contains `gui/resources/icon.svg`, the size PNGs, `data/systemimgkit.desktop`, and the hicolor PNG tree
