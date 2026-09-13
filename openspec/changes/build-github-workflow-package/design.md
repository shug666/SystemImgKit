## Context

SystemImgKit is a PySide6 + QML desktop tool for unpacking/debloating/repacking Android ext4 system images. It currently installs only via `git clone` + `pip install .`, requiring the user to supply Python ≥ 3.12 and PySide6. The target deployment machine is **Ubuntu 20.04.6**, whose default Python is 3.8 — so the current install path is unavailable to the intended user without manual PPA setup. We want a GitHub Actions workflow that freezes the GUI into a portable package the user can extract and run on 20.04.6 with no Python/Qt toolchain of their own.

Two hard constraints shape the design:

1. **glibc downward compatibility.** A binary built against a newer glibc cannot run on an older one. GitHub-hosted `ubuntu-20.04` runners were retired in 2025, so we cannot build directly on a 20.04 host. We must build inside a **`container: ubuntu:20.04`** (glibc 2.31) on an `ubuntu-latest` job so the frozen artifacts run on 20.04.6.
2. **The root-helper subprocess chain.** The GUI runs as a normal user; unpack/pack's high-fidelity path needs root and delegates to `systemimgkit.root_helper` launched via `pkexec sys.executable -m systemimgkit.root_helper`. Under PyInstaller, `sys.executable` is the frozen GUI exe and `-m` cannot import packaged modules — this chain breaks. This is the single most important integration detail: a GUI frozen without addressing it will run but fail the moment the user tries unpack/pack.

PySide6, bundled `ext4tools/linux-x86_64/{mke2fs,e2fsdroid}` (precompiled, already 20.04-compatible), the `qml_rc.py` compiled QML resources, and `pkexec`/policykit-1 (20.04-native) are all available on the target.

## Goals / Non-Goals

**Goals:**
- Produce a portable `tar.gz` that extracts to a directory runnable on Ubuntu 20.04.6 x86_64 with zero local Python/Qt toolchain — double-click or CLI launch, GUI works.
- The frozen package's root-privilege chain (GUI → `pkexec` → root_helper → mke2fs/e2fsdroid) works identically to the dev environment.
- Bundle the precompiled ext4 tools and YAML/desktop/icon resources inside the package.
- Ship an `install-deps.sh` that installs the host-level runtime deps (e2fsprogs, rsync, etc.) the frozen package cannot bundle.
- Trigger on tag (`v*`) and publish artifacts to a GitHub Release; also runnable via `workflow_dispatch`.

**Non-Goals:**
- Supporting distributions/architectures other than Ubuntu 20.04.6 x86_64.
- Producing a `.deb` (binding PySide6 + a non-system Python into a deb is inelegant and low-value; the portable tarball satisfies the "installable package" need more cleanly).
- Producing an AppImage as the default (the read-only-squashfs mount + random mountpoint + root-spawned second-exe interaction adds risk for marginal benefit; revisit later if a single-file artifact is wanted).
- Bundling `e2fsprogs`/`rsync`/`adb`/`fastboot` inside the package — these are host system packages and stay in `install-deps.sh`.
- Cross-platform Windows/macOS builds.
- CI for tests/lint in this change (separate concern; this workflow is release-packaging only).

## Decisions

### D1: Build inside `container: ubuntu:20.04` on an `ubuntu-latest` job
Build where glibc ≤ the target's. `ubuntu-20.04` hosted runners are gone; the container restores the 2.31 baseline. Alternatives considered: (a) build on `ubuntu-latest` directly — rejected, glibc 2.39 artifacts fail on 20.04 with `GLIBC_2.34 not found`; (b) pin an older action-runner image — rejected, unmaintained. The container keeps the job definition portable and the host-runner concern (glibc) explicit.

### D2: Python 3.12 via deadsnakes PPA inside the container
20.04's base repo has only Python 3.8; the project requires ≥ 3.12. The deadsnakes PPA ships `python3.12` for focal. Alternatives: (a) build Python from source in CI — slow, fragile; (b) drop to 3.8 and rewrite `from __future__` / typing usage — out of scope and regressive. Deadsnakes is the standard, low-risk path.

### D3: PyInstaller `onedir` (not `onefile`), two entry scripts
`onedir` keeps the GUI exe and a **separate frozen `root_helper` exe** as two ordinary files side-by-side in one directory — no squashfs mount, no random mountpoint, just relative paths. This minimizes the risk of the pkexec + second-exe interaction (D6). `onefile` would extract to a temp dir each launch, complicating the helper path resolution. Two entries:
- `systemimgkit` → `systemimgkit.gui.app.main` (the GUI).
- `root_helper` → `systemimgkit.root_helper.main` (the headless privileged helper).

The helper never imports PySide6 (already true), so freezing it as a second entry adds little weight and avoids pulling Qt into its bundle.

### D4: `rootops._helper_module()` gains a frozen-environment branch
Current: `return [sys.executable, "-m", "systemimgkit.root_helper"]`. New behavior uses `getattr(sys, "frozen", False)`:
- Frozen: `return [<dist dir>/root_helper]` (the sibling executable, resolved relative to the GUI exe via `os.path.dirname(sys.executable)`).
- Dev: unchanged (`sys.executable -m systemimgkit.root_helper`).

This is the one runtime code change required by packaging. It is backward-compatible — dev behavior is identical.

### D5: PyInstaller spec bundles data files and declares QML hidden-imports
- **datas**: `ext4tools/linux-x86_64/*` (the precompiled mke2fs/e2fsdroid), `data/*.yaml` (guardlist), `data/*.desktop`, the icon tree. `qml_rc.py` is already Python and gets imported normally.
- **hiddenimports**: the QML engine plugins PyInstaller's PySide6 hook does not always detect — `QtQuick`, `QtQuick.Controls`, `QtQuick.Layouts`, `QtQuick.Dialogs`, `QtQuick.Effects` (the QML uses `MultiEffect`, Qt 6.5+ native — **not** Qt5Compat, confirmed), and `QtQml.Models`. These are the most likely runtime "module not installed" failures; declaring them up front reduces iteration.
- A runtime hook may be needed to set `QT_PLUGIN_PATH` / `QML2_IMPORT_PATH` to the bundled plugin dirs if PyInstaller's relocation breaks Qt's default resolution. Plan for it, validate empirically.

### D6: System deps via `install-deps.sh`, not bundled
The frozen package cannot (and should not) ship `e2fsprogs`, `rsync`, `img2simg`, `adb`, `fastboot` — they are host packages with their own lifecycle. Qt6 GUI runtime libs (`libgl1`, `libegl1`, `libxkbcommon0`, `libdbus-1-3`) and `policykit-1` (for `pkexec`) are also host-level and declared in the script. The script is `apt`-based and idempotent. The workflow installs these same packages in the build container so the build environment mirrors the runtime.

### D7: Trigger on `v*` tag → GitHub Release, plus `workflow_dispatch`
Tagging produces a stable, linkable release artifact; manual dispatch allows one-off builds during iteration. The workflow uploads the `tar.gz` and `install-deps.sh` to a Release created via `softprops/action-gh-release` (or equivalent) keyed on the tag.

## Risks / Trade-offs

- **[Risk] QML hidden-imports incomplete → "module QtQuick.X is not installed" at launch.** → Mitigation: declare the known set in D5; iterate against the actual frozen artifact on a 20.04 host (or a 20.04 test container) until the GUI renders; log which plugins were bundled.
- **[Risk] Qt plugin path resolution broken under `onedir` relocation → blank window / SVG icons missing.** → Mitigation: runtime hook setting `QT_PLUGIN_PATH`/`QML2_IMPORT_PATH`; fall back to the rasterized PNG icon path the app already has (`app.py` already tries PNG when SVG plugin is absent).
- **[Risk] `root_helper` frozen exe path resolution wrong → pkexec fails / GUI can't unpack.** → Mitigation: resolve the helper via `os.path.dirname(sys.executable)` (stable relative location in onedir); add a startup self-check in the GUI that verifies the helper path exists and surface a clear error if not.
- **[Risk] The bundled `mke2fs`/`e2fsdroid` lose execute bits or library deps under PyInstaller data packaging.** → Mitigation: mark them `binaries` (not `datas`) in the spec so PyInstaller preserves executability and tracks their lib deps; `chmod +x` defensively.
- **[Risk] glibc of bundled ext4tools vs container.** The precompiled tools already run on the user's 20.04.6, so they are compatible by construction; verify they also run inside the ubuntu:20.04 build container.
- **[Trade-off] Package size (~120MB) due to bundled PySide6 + Qt.** → Accepted: it removes the user's need to install a Qt toolchain. Out of scope to slim further.
- **[Trade-off] `onedir` is a directory, not a single file.** → Accepted per D3 (helper-chain stability outweighs single-file convenience). An AppImage layer could be added later on top of a working onedir.

## Open Questions

- Exact QML plugin set required at runtime — to be confirmed empirically by running the frozen artifact; the D5 list is the best-effort starting point.
- Whether a runtime hook for `QT_PLUGIN_PATH`/`QML2_IMPORT_PATH` is actually needed (PyInstaller's PySide6 hook may handle it) — decide after first frozen run.
- Naming/versioning of the release artifact (e.g. `SystemImgKit-{tag}-ubuntu-20.04-x86_64.tar.gz`) — confirm desired scheme during implementation.
