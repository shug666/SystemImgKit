## 1. Runtime code change for the frozen root helper

- [x] 1.1 Modify `systemimgkit/gui/rootops.py::_helper_module()` to detect `getattr(sys, "frozen", False)` and, when frozen, return the path to the sibling `root_helper` executable resolved via `os.path.dirname(sys.executable)`; keep the dev branch (`sys.executable -m systemimgkit.root_helper`) unchanged
- [x] 1.2 Add a guard that, in the frozen branch, verifies the resolved helper path exists and surfaces a clear error (raise `SystemImgKitError` with a descriptive message) if the `root_helper` executable is missing, instead of failing opaquely inside pkexec
- [x] 1.3 Verify dev behavior is unchanged: run the GUI from source and confirm `_helper_module()` still returns `[sys.executable, "-m", "systemimgkit.root_helper"]`

## 2. PyInstaller spec

- [x] 2.1 Create `packaging/systemimgkit.spec` defining two `Analysis`/`EXE`/`COLLECT` entries in `onedir` mode: `systemimgkit` (entry `systemimgkit.gui.app:main`) and `root_helper` (entry `systemimgkit.root_helper:main`)
- [x] 2.2 Declare `datas` for `ext4tools/linux-x86_64/*` (as binaries to preserve the exec bit and track lib deps), `data/*.yaml` (guardlist), `data/*.desktop`, and the `data/icons` tree
- [x] 2.3 Declare `hiddenimports` for the QML plugins: `QtQuick`, `QtQuick.Controls`, `QtQuick.Layouts`, `QtQuick.Dialogs`, `QtQuick.Effects`, `QtQml.Models`
- [x] 2.4 Ensure both executables end up in the same `onedir` root directory (shared `dist/systemimgkit/`), so `os.path.dirname(sys.executable)` resolves the sibling helper
- [x] 2.5 Add a runtime hook (`packaging/hook-runtime.py` or `rthooks`) setting `QT_PLUGIN_PATH`/`QML2_IMPORT_PATH` to the bundled plugin dirs if needed (decide empirically after first frozen run)

## 3. Host dependency installer

- [x] 3.1 Create `install-deps.sh` (idempotent, apt-based) installing: `e2fsprogs`, `rsync`, `img2simg` (or `android-tools-fsutils`), `adb`, `fastboot`, `policykit-1`, and Qt6 GUI runtime libs (`libgl1`, `libegl1`, `libxkbcommon0`, `libdbus-1-3`)
- [ ] 3.2 Make `install-deps.sh` executable and verify it runs cleanly on a fresh ubuntu:20.04 container

## 4. GitHub Actions workflow

- [x] 4.1 Create `.github/workflows/release.yml` with an `ubuntu-latest` job using `container: ubuntu:20.04`
- [x] 4.2 In the container: add deadsnakes PPA, install `python3.12` + `python3-pip`, and the same host deps as `install-deps.sh` (so the build env mirrors runtime)
- [x] 4.3 `pip install` PySide6, PyYAML, pyinstaller; then `pip install -e .` (or install the project) so entry points resolve
- [x] 4.4 Run PyInstaller with `packaging/systemimgkit.spec` (both entries), then `tar -czf` the `onedir` into `SystemImgKit-<tag>-ubuntu-20.04-x86_64.tar.gz`
- [x] 4.5 Add `workflow_dispatch` trigger; on tag (`v*`) create a GitHub Release and upload the `tar.gz` and `install-deps.sh` as assets (e.g. `softprops/action-gh-release`)
- [x] 4.6 On non-tag (`workflow_dispatch`) runs, upload the artifacts via `actions/upload-artifact` for iteration

## 5. Validation

- [ ] 5.1 Run the workflow via `workflow_dispatch`; download the `tar.gz` + `install-deps.sh`
- [ ] 5.2 On a clean ubuntu:20.04 container (or the 20.04.6 target host), run `install-deps.sh`, extract the `tar.gz`, and launch `systemimgkit` — confirm the QML GUI renders (no "module not installed" errors, icons show)
- [ ] 5.3 In the frozen GUI, open a real `system.img` and trigger unpack — confirm the `pkexec → root_helper → mke2fs` chain works (helper resolves, root operation completes)
- [ ] 5.4 Trigger a pack operation — confirm the frozen `mke2fs`/`e2fsdroid` bundled binaries execute and produce `system_new.img` + `flash.sh`
- [ ] 5.5 If QML plugin or Qt path issues appear, iterate on hidden-imports/runtime hook in `packaging/systemimgkit.spec` until the frozen GUI runs clean

## 6. Finalize

- [x] 6.1 Confirm the artifact naming scheme (`SystemImgKit-<tag>-ubuntu-20.04-x86_64.tar.gz`) matches the release step
- [x] 6.2 Update README with a "下载安装包" section pointing to the GitHub Release and documenting `install-deps.sh` + extract + launch
