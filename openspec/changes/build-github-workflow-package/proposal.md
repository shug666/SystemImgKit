## Why

SystemImgKit 目前只能通过 `git clone` + `pip install .` 安装，需要用户自行准备 Python ≥ 3.12 和 PySide6 环境——Ubuntu 20.04.6 默认只有 Python 3.8，用户无法直接使用。需要一个 GitHub Actions 工作流，把 GUI 应用（含 Python 运行时、PySide6、内置 ext4 工具）冻结成一个可在 Ubuntu 20.04.6 上解压即用的便携安装包，并附带的系统依赖安装脚本，降低分发与使用门槛。

## What Changes

- 新增 GitHub Actions workflow（`.github/workflows/release.yml`）：在 `ubuntu-latest` job 内嵌 **`container: ubuntu:20.04`** 构建（glibc 2.31，保证产物兼容 20.04.6），通过 deadsnakes PPA 装 Python 3.12，用 PyInstaller onedir 冻结两个入口可执行文件，打包成 `tar.gz` 便携包。
- 新增 **第二个 PyInstaller 入口 `root_helper`**（独立冻结可执行），供 GUI 通过 `pkexec` 以 root 调用；并在 `gui/rootops.py::_helper_module()` 中用 `getattr(sys, "frozen", False)` 区分冻结环境（调用同目录的 `root_helper` 可执行）与 dev 环境（沿用 `sys.executable -m systemimgkit.root_helper`），使冻结后 root 提权子进程链不断裂。
- 新增 PyInstaller hook/spec：把 `systemimgkit/ext4tools/linux-x86_64/*`、`data/*.yaml`、`data/*.desktop`、图标资源作为 data 文件打入包，并声明 QML 引擎的 hidden-imports（`QtQuick`、`QtQuick.Controls`、`QtQuick.Layouts`、`QtQuick.Dialogs`、`QtQuick.Effects`、`QtQml.Models`）。
- 新增 `install-deps.sh`：安装运行期宿主级系统依赖（`e2fsprogs`、`rsync`、`img2simg`、`adb`、`fastboot`、`policykit-1`、Qt6 GUI 所需的 GL/EGL/xkbcommon/dbus 运行库），随便携包一起分发。
- **触发方式**：打 tag（`v*`）触发构建，产物挂到 GitHub Release；workflow 也可手动 `workflow_dispatch`。

## Capabilities

### New Capabilities
- `ci-release-packaging`: 在 GitHub Actions 上将 SystemImgKit 冻结成兼容 Ubuntu 20.04.6 的便携安装包（含 GUI、Python 运行时、PySide6、内置 ext4 工具），打 tag 自动产出并发布到 GitHub Release。

### Modified Capabilities
- `gui`: root helper 子进程的调用方式需在冻结环境下改变——`rootops._helper_module()` 必须区分冻结/dev 环境，冻结时调用同目录的独立 `root_helper` 可执行文件，否则冻结后 pkexec 提权链断裂、GUI 打包即废。

## Impact

- **新增文件**：`.github/workflows/release.yml`、PyInstaller spec 文件（如 `packaging/systemimgkit.spec`）、`install-deps.sh`、可能的 `packaging/` 目录。
- **修改文件**：`systemimgkit/gui/rootops.py`（`_helper_module()` 增加冻结分支）。
- **依赖**：构建期引入 `pyinstaller`、`PySide6`（已为运行期依赖）、deadsnakes PPA；运行期宿主依赖由 `install-deps.sh` 声明。
- **兼容性**：构建在 ubuntu:20.04 容器内进行以匹配目标机 glibc；产物面向 Ubuntu 20.04.6 x86_64，不覆盖其他发行版/架构。
- **风险**：PyInstaller 打包 PySide6 QML 应用的 hidden-import 需迭代调试；root helper 双入口在 pkexec + 冻结二进制下的路径解析需验证。
