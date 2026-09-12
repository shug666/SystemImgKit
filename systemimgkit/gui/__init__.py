"""QtQuick (QML) desktop GUI for SystemImgKit.

Importing this package imports PySide6; the CLI (systemimgkit.cli) never imports
this package, so the CLI runs on systems without PySide6. The view layer is
authored in QML (`qml/main.qml`) and bound to the backend through the
`Controller` singleton and the item models in `models.py`.
"""

from .app import run_gui  # noqa: F401

