# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SystemImgKit.

Builds TWO frozen executables into ONE onedir bundle (`dist/systemimgkit/`):
  - `systemimgkit`  → the PySide6 QML GUI (systemimgkit.gui.app.run_gui)
  - `root_helper`   → the headless privileged helper (systemimgkit.root_helper.main)

The GUI runs as a normal user; unpack/pack delegate root work to `root_helper`
via `pkexec`. In the frozen environment `gui/rootops._helper_module()` resolves
the sibling `root_helper` executable via `os.path.dirname(sys.executable)`, so
BOTH executables MUST land in the same onedir root directory (this spec's
single COLLECT guarantees that).

Built inside a `container: ubuntu:20.04` (glibc 2.31) so the artifacts run on
Ubuntu 20.04.6. Run with:

    pyinstaller packaging/systemimgkit.spec --noconfirm
"""

from __future__ import annotations

import glob
import os

# Resolve paths relative to the repo root (the spec lives in packaging/).
REPO_ROOT = os.path.dirname(os.path.abspath(SPECPATH))
PKG = os.path.join(REPO_ROOT, "systemimgkit")

# --- Bundled Android ext4 tools (precompiled, exec bit must be preserved) ---
# These are binaries, not data: PyInstaller tracks their library dependencies
# and keeps the executable bit. tools.py locates them via __file__-relative path
# `systemimgkit/ext4tools/linux-x86_64`, so the target dir mirrors that.
ext4_binaries = [
    (src, os.path.join("systemimgkit", "ext4tools", "linux-x86_64"))
    for src in glob.glob(os.path.join(PKG, "ext4tools", "linux-x86_64", "*"))
]

# --- Data files (guardlist yaml, .desktop, icon tree) ---
# Package modules resolve these via os.path.dirname(__file__)/... so target
# paths must mirror the in-package layout (systemimgkit/data/...).
_data_target = os.path.join("systemimgkit", "data")
data_files = [
    (os.path.join(PKG, "data", "guardlist.yaml"), _data_target),
    (os.path.join(PKG, "data", "systemimgkit.desktop"), _data_target),
    # Icon tree (recursive). PyInstaller maps a source dir → target dir.
    (os.path.join(PKG, "data", "icons"),
     os.path.join("systemimgkit", "data", "icons")),
]

# --- QML hidden-imports PyInstaller's PySide6 hook does not always detect ---
# main.qml imports: QtQuick, QtQuick.Controls, QtQuick.Layouts, QtQuick.Dialogs,
# QtQuick.Effects (MultiEffect, Qt 6.5+ native — NOT Qt5Compat), plus the
# models plugin backing the Python list models.
qml_hiddenimports = [
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickLayouts",
    "PySide6.QtQuickDialogs",
    "PySide6.QtQuick3D",  # pulls QtQuick.Effects/MultiEffect plugin
    "PySide6.QtQml",
]

hiddenimports = [
    *qml_hiddenimports,
    "systemimgkit",
    "systemimgkit.gui",
    "systemimgkit.gui.qml_rc",  # compiled QML resources (registers :/qml, :/icons)
    "systemimgkit.root_helper",
    "yaml",
]

# Runtime hook for Qt plugin/qml import paths (set defensively; harmless if
# PyInstaller's PySide6 hook already resolves them).
runtime_hooks = [os.path.join(REPO_ROOT, "packaging", "rthook_qt.py")]


# --- GUI Analysis ---------------------------------------------------------
gui_a = Analysis(
    [os.path.join(PKG, "gui", "app.py")],
    pathex=[REPO_ROOT],
    binaries=ext4_binaries,
    datas=data_files,
    hiddenimports=hiddenimports,
    runtime_hooks=runtime_hooks,
    excludes=["tkinter", "PyQt5", "PyQt6"],
    noarchive=False,
)

# --- Root helper Analysis ------------------------------------------------
# The helper never imports PySide6, so its bundle is much smaller. It does not
# need the QML hidden-imports or icon tree; only the shared ext4tools binaries
# and guardlist yaml (which COLLECT dedups with the GUI's copies).
helper_a = Analysis(
    [os.path.join(PKG, "root_helper.py")],
    pathex=[REPO_ROOT],
    binaries=ext4_binaries,
    datas=data_files,
    hiddenimports=["systemimgkit", "systemimgkit.root_helper", "yaml"],
    excludes=["tkinter", "PyQt5", "PyQt6"],
    noarchive=False,
)

# Modern PyInstaller 6.x onedir pattern: bytecode (`pure`) goes into a PYZ
# archive, EXE takes only scripts with `exclude_binaries=True`, and the
# binaries/datas are placed by COLLECT. Passing `pure` straight into EXE (the
# old onefile-style pattern) trips the `BYTECODE_MAGIC` assertion during PKG
# assembly.
gui_pyz = PYZ(gui_a.pure)
gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    [],
    exclude_binaries=True,
    name="systemimgkit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app: no terminal window
)

helper_pyz = PYZ(helper_a.pure)
helper_exe = EXE(
    helper_pyz,
    helper_a.scripts,
    [],
    exclude_binaries=True,
    name="root_helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # helper talks over stdout/stderr protocol; keep stdio
)

# Single COLLECT merges both executables + their binaries/datas into one
# onedir: dist/systemimgkit/. This is what makes the sibling-helper resolution
# in rootops._helper_module() work — both exes sit side by side at the onedir
# root. COLLECT dedups shared binaries/datas (ext4tools, guardlist, icons).
COLLECT(
    gui_exe,
    helper_exe,
    gui_a.binaries,
    gui_a.datas,
    helper_a.binaries,
    helper_a.datas,
    name="systemimgkit",
    strip=False,
    upx=False,
)
