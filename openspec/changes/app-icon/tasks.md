## 1. 图标设计稿（SVG 母稿）

- [x] 1.1 绘制 `systemimgkit/gui/resources/icon.svg`：三层堆叠方块，分别用 guard 调色板（core `#D43A3A` / guarded `#C8821A` / ok `#1F9D55`），容器/描边为高对比深色 keyline；设计画布 ≥128，保证 16px 下每条 band 仍可辨
- [x] 1.2 在浅色与深色背景上目检 SVG，确认三条 band 在两种背景下均清晰可辨（无需单色变体）

## 2. 光栅化 PNG（多尺寸）

- [x] 2.1 用 `rsvg-convert`（或 `inkscape`）从 `icon.svg` 生成 16/22/24/32/48/64/128/256 px PNG，输出到 `systemimgkit/gui/resources/`（命名 `icon-16.png` … `icon-256.png`）
- [x] 2.2 单独检查 16px PNG：必要时手工微调/重绘 16px 版本，保证三条 band 不糊成一团
- [x] 2.3 把 256px 版本同时作为 `.desktop`/hicolor 的来源（见任务 5）

## 3. 注册到 Qt 资源系统

- [x] 3.1 在 `systemimgkit/gui/qml.qrc` 新增 `<qresource prefix="/">`，登记 `resources/icon.svg`（alias `icon.svg`）与各 PNG（alias `icon-16.png` … `icon-256.png`）
- [x] 3.2 运行 `pyside6-rcc` 重新生成 `systemimgkit/gui/qml_rc.py`
- [x] 3.3 验证 dev 模式与 qrc 模式下 `:/icon.svg`、`:/icon-256.png` 均可解析（在 `app.py` 资源加载分支两路都走通）

## 4. 设置窗口图标

- [x] 4.1 在 `systemimgkit/gui/app.py` 的 `run_gui` 中、`app.setApplicationName(...)` 之后调用 `app.setWindowIcon(QIcon(":/icon.svg"))`；用 try/except 在 SVG 不可用时回退到 `QIcon(":/icon-256.png")`
- [x] 4.2 启动 GUI，确认标题栏与任务栏显示图标（非通用/空白图标）
- [x] 4.3 确认 dev（文件系统）与 installed（qrc）两种加载分支下窗口图标均生效

## 5. Linux Shell 集成（.desktop + hicolor）

- [x] 5.1 创建 `systemimgkit/data/systemimgkit.desktop`：Type=Application、Name=SystemImgKit、Comment（中文：Android system.img 精简工具）、Exec=systemimgkit、Icon=systemimgkit、Terminal=false、Categories=System;Utility
- [x] 5.2 创建 `systemimgkit/data/icons/hicolor/{16x16,22x22,24x24,32x32,48x48,64x64,128x128,256x256}/apps/systemimgkit.png`，由任务 2 的对应尺寸 PNG 复制/链接而来
- [x] 5.3 实现安装步骤：将 `.desktop` 与 hicolor 图标复制到用户级 `~/.local/share/applications` 与 `~/.local/share/icons/hicolor/.../apps/`（在 `cli.py` 增加一个 `install-icons` 子命令或在 README 文档化手动安装命令）
- [x] 5.4 验证 `gtk-launch systemimgkit` 或菜单中能按图标找到并启动应用（前提：`systemimgkit` 在 PATH 上）

## 6. 打包与分发

- [x] 6.1 在 `pyproject.toml` 的 `[tool.setuptools.package-data]` 中补充 `gui/resources/*.svg`、`gui/resources/*.png`、`data/*.desktop`、`data/icons/hicolor/*/*/*.png`
- [x] 6.2 确认 `pip install .` 后 wheel/sdist 内含图标资源、`.desktop` 与 hicolor PNG
- [x] 6.3 冒烟：全新 venv 安装后启动 GUI，窗口图标存在；运行 `install-icons` 后菜单出现 SystemImgKit

## 7. 文档

- [x] 7.1 在 README 增加一节说明图标安装方式（`install-icons` 子命令或手动 `~/.local/share` 拷贝）及 PATH 前置条件
- [x] 7.2 更新 `gui-qml-migration` 相关说明（若 README 引用了资源清单，补上 `resources/`）
