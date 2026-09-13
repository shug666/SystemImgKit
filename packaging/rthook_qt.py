# -*- coding: utf-8 -*-
"""PyInstaller runtime hook: point Qt at the bundled plugin/qml dirs.

Defensive: PyInstaller's PySide6 hook usually sets these up already. This hook
ensures `QT_PLUGIN_PATH` and `QML2_IMPORT_PATH` resolve under the frozen
`_internal/` tree even if the hook's defaults are wrong, so the QML engine finds
`QtQuick`/`QtQuick.Controls`/... and the GUI renders instead of erroring with
"module is not installed".

Harmless when the dirs already resolve correctly — we only prepend bundled
paths that exist.
"""

import os
import sys

_frozen_dir = os.path.dirname(sys.executable)  # onedir root (sibling of _internal)
_internal = os.path.join(_frozen_dir, "_internal")
if not os.path.isdir(_internal):
    # Older PyInstaller layout (no _internal/): libs live next to the exe.
    _internal = _frozen_dir


def _prepend(env_var, *candidates):
    existing = os.environ.get(env_var, "")
    parts = [p for p in existing.split(os.pathsep) if p]
    for c in candidates:
        if c and os.path.isdir(c) and c not in parts:
            parts.insert(0, c)
    if parts:
        os.environ[env_var] = os.pathsep.join(parts)


# Qt plugins (platforms, imageformats, iconengines, platforminputcontexts, ...)
_prepend("QT_PLUGIN_PATH",
         os.path.join(_internal, "PySide6", "plugins"),
         os.path.join(_internal, "plugins"))

# QML imports (QtQuick, QtQuick.Controls, ...)
_prepend("QML2_IMPORT_PATH",
         os.path.join(_internal, "PySide6", "qml"),
         os.path.join(_internal, "qml"))
