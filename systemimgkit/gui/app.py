"""GUI 应用入口（QtQuick / QML 版）。

GUI 以普通用户身份运行 —— 这样系统原生文件对话框能正常访问用户家目录
（root 进程的 GTK 对话框看不到 /home/user）。需要 root 的操作（解包/打包）
不在启动时整进程提权，而是在操作时通过 root helper 子进程（一次 pkexec）
完成，见 gui/rootops.py 与 root_helper.py。

dev 环境从文件系统加载 .qml，安装环境从 qrc 加载。
"""

from __future__ import annotations

import os
import sys


def _qml_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml")


def _set_window_icon(app) -> None:
    """Apply the SystemImgKit application icon to the window.

    Tries the SVG from the Qt resource system first (registering the qrc
    resources so ``:/`` resolves in dev mode too), then falls back to the SVG
    on the filesystem, then to a rasterized PNG (in case the Qt SVG image
    plugin is unavailable). The window always ends up with an icon.
    """
    from PySide6.QtGui import QIcon

    # Register the qrc resources first so ":/icon.svg" resolves in dev mode
    # (where qml_rc is otherwise imported lazily only on the installed branch).
    from . import qml_rc  # noqa: F401  (registers the :/ resources)

    icon = QIcon(":/icon.svg")
    if icon.isNull():
        fs_svg = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "resources", "icon.svg")
        if os.path.isfile(fs_svg):
            icon = QIcon(fs_svg)
    if icon.isNull():
        # No Qt SVG image plugin available — use a rasterized PNG from the qrc.
        icon = QIcon(":/icon-256.png")
    app.setWindowIcon(icon)


def run_gui(args=None) -> int:
    """启动 GUI（普通用户身份）。

    `args` 来自 argparse；此处不再使用 --elevated/--orig-uid（整进程提权已移除）。
    """
    from PySide6.QtCore import QLocale, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
    from .controller import Controller

    app = QGuiApplication(sys.argv)
    app.setApplicationName("SystemImgKit")
    _set_window_icon(app)
    QLocale.setDefault(QLocale(QLocale.Chinese, QLocale.China))

    controller = Controller()
    controller.set_title("SystemImgKit — system.img 精简工具")
    # 普通用户模式：解包/打包时各弹一次 pkexec 授权。
    controller.set_startup_warnings([
        "以普通用户模式运行：文件选择可访问任意目录。",
        "解包/打包时将弹出系统授权窗口，请输入密码以完成 root 操作。",
    ])

    # Register the Controller as a QML singleton BEFORE creating the engine.
    # Registering while an engine already exists triggers a Qt 6.9 Universal
    # style import-cache bug ("QQuickUniversalFocusRectangle ... contentData").
    qmlRegisterSingletonInstance(Controller, "SystemImgKit", 1, 0, "Controller", controller)

    engine = QQmlApplicationEngine()

    # Load: prefer filesystem (dev), fall back to qrc (installed).
    qml_main = os.path.join(_qml_dir(), "main.qml")
    if os.path.isfile(qml_main):
        engine.addImportPath("file://" + _qml_dir())
        engine.load(QUrl.fromLocalFile(qml_main))
    else:
        # Compiled resources (see qml.qrc → qml_rc.py via pyside6-rcc).
        from . import qml_rc  # noqa: F401  (registers the :/qml resources)
        engine.load(QUrl("qrc:/qml/main.qml"))

    if not engine.rootObjects():
        return 1
    rc = app.exec()
    # On exit, cleanly stop any in-flight background worker before the QThread
    # is destroyed (otherwise "QThread: Destroyed while still running" crashes
    # the process when unpack/pack was still going as the window closed).
    worker = controller._worker
    if worker is not None and worker.isRunning():
        worker.cancel()
        worker.wait(5000)
    return rc
