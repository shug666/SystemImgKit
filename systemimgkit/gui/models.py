"""QML-facing item models for the SystemImgKit GUI.

`AppCardModel` drives the card-style catalog `ListView`; `FileTreeModel`
drives the compact "Files (advanced)" view. Guard/selection rules live in
these Python models (see design D3) — the QML views only render roles and
forward user intent; they cannot authorize a deletion.
"""

from __future__ import annotations

import os

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, Qt, Slot, Signal,
)

from .. import catalog
from ..catalog import AppEntry, Catalog, GuardLevel


# ---- role names -------------------------------------------------------------

_APP_ROLES = {
    Qt.ItemDataRole.DisplayRole + 0x0100: b"name",
    Qt.ItemDataRole.DisplayRole + 0x0101: b"partition",
    Qt.ItemDataRole.DisplayRole + 0x0102: b"privilege",
    Qt.ItemDataRole.DisplayRole + 0x0103: b"imagePath",
    Qt.ItemDataRole.DisplayRole + 0x0104: b"size",
    Qt.ItemDataRole.DisplayRole + 0x0105: b"fileCount",
    Qt.ItemDataRole.DisplayRole + 0x0106: b"guard",       # "none"|"guarded"|"core"
    Qt.ItemDataRole.DisplayRole + 0x0107: b"checked",
    Qt.ItemDataRole.DisplayRole + 0x0108: b"guardReason",
    Qt.ItemDataRole.DisplayRole + 0x0109: b"section",    # group key: "system/app"
    Qt.ItemDataRole.DisplayRole + 0x010a: b"sectionLabel", # 中文标签
}

_NAME = Qt.ItemDataRole.DisplayRole + 0x0100
_PARTITION = Qt.ItemDataRole.DisplayRole + 0x0101
_PRIVILEGE = Qt.ItemDataRole.DisplayRole + 0x0102
_IMAGEPATH = Qt.ItemDataRole.DisplayRole + 0x0103
_SIZE = Qt.ItemDataRole.DisplayRole + 0x0104
_FILECOUNT = Qt.ItemDataRole.DisplayRole + 0x0105
_GUARD = Qt.ItemDataRole.DisplayRole + 0x0106
_CHECKED = Qt.ItemDataRole.DisplayRole + 0x0107
_GUARDREASON = Qt.ItemDataRole.DisplayRole + 0x0108
_SECTION = Qt.ItemDataRole.DisplayRole + 0x0109
_SECTIONLABEL = Qt.ItemDataRole.DisplayRole + 0x010a

_GUARD_STR = {
    GuardLevel.NONE: "none",
    GuardLevel.GUARDED: "guarded",
    GuardLevel.CORE: "core",
}

# 中文目录标签（partition/privilege → 可读名）
_SECTION_LABELS = {
    ("system", "app"): "系统 · 普通应用",
    ("system", "priv-app"): "系统 · 特权应用",
    ("system", "preinstall"): "系统 · 预装应用（ZUI 内置）",
    ("product", "app"): "产品 · 普通应用",
    ("product", "priv-app"): "产品 · 特权应用",
    ("system_ext", "app"): "扩展 · 普通应用",
    ("system_ext", "priv-app"): "扩展 · 特权应用",
}


def _section_key(entry: AppEntry) -> str:
    return f"{entry.partition}/{entry.privilege}"


def _section_label(entry: AppEntry) -> str:
    return _SECTION_LABELS.get((entry.partition, entry.privilege),
                               f"{entry.partition}/{entry.privilege}")


def _guard_reason(entry: AppEntry) -> str:
    if entry.guard is GuardLevel.CORE:
        return f"核心系统应用 —— 不可删除。\n{entry.image_path}"
    if entry.guard is GuardLevel.GUARDED:
        return f"受保护 —— 需开启风险覆盖开关。\n{entry.image_path}"
    return f"可删除。\n{entry.image_path}"


class AppCardModel(QAbstractListModel):
    """Flat list model of catalog apps, one row per app directory.

    Owns the guard/selection rules. `risk_override` is toggled by the
    Controller; when False, guarded entries refuse to be checked.
    """

    # (app_name, reason) emitted when a view-side check is refused by guard.
    guardBlocked = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._apps: list[AppEntry] = []
        self._checked: list[bool] = []
        self._risk_override: bool = False
        self._sort_key: str = "name"
        self._sort_desc: bool = False
        self._filter_section: str | None = None  # None = show all directories
        self._visible: list[int] = []

    # ---- loading ----

    def set_catalog(self, cat: Catalog) -> None:
        self._apps = list(cat.apps)
        self._checked = [False] * len(self._apps)
        self._filter_section = None
        self._apply_sort()  # sorts + resets model

    @Slot(str)
    def setFilterSection(self, section: str) -> None:
        """Show only apps in `section` (e.g. "system/priv-app").

        Pass "" to show all directories. Re-sorts and resets the model.
        """
        target = section.strip() if section else ""
        self._filter_section = target or None
        self._apply_sort()

    @Slot(result="QVariantList")
    def sections(self) -> list:
        """Return [{key, label, count}] for every directory that has apps,
        in catalog.APP_DIRS order."""
        _dir_order = {
            ("system", "app"): 0, ("system", "priv-app"): 1,
            ("system", "preinstall"): 2, ("product", "app"): 3,
            ("product", "priv-app"): 4, ("system_ext", "app"): 5,
            ("system_ext", "priv-app"): 6,
        }

        def order_of(key: str) -> int:
            parts = key.split("/")
            return _dir_order.get((parts[0], "/".join(parts[1:])), 99)

        counts: dict[str, int] = {}
        for app in self._apps:
            k = _section_key(app)
            counts[k] = counts.get(k, 0) + 1
        out = []
        for k in sorted(counts.keys(), key=order_of):
            rep = next(a for a in self._apps if _section_key(a) == k)
            out.append({"key": k, "label": _section_label(rep), "count": counts[k]})
        return out

    # ---- override / sort ----

    def set_risk_override(self, on: bool) -> bool:
        """Toggle override. Returns False (with side effect: unchecking
        guarded entries that are no longer selectable) when turning it off."""
        if on == self._risk_override:
            return True
        self._risk_override = on
        # Turning override off must drop any guarded selections.
        if not on:
            changed = False
            for i, app in enumerate(self._apps):
                if self._checked[i] and app.guard is GuardLevel.GUARDED:
                    self._checked[i] = False
                    changed = True
            if changed and self._visible:
                # refresh all visible rows (guard/enabled state changed)
                self.dataChanged.emit(self.index(0), self.index(len(self._visible) - 1))
            return not changed
        return True

    @property
    def risk_override(self) -> bool:
        return self._risk_override

    @Slot(str, bool)
    def sort(self, key: str = "name", desc: bool = False) -> None:
        """Reorder rows by key: 'name' | 'size' | 'guard'.

        `desc` reverses the within-directory order. Directory grouping is always
        ascending (catalog.APP_DIRS order).
        """
        self._sort_key = key
        self._sort_desc = desc
        self._apply_sort()

    def _apply_sort(self) -> None:
        if not self._apps:
            return
        # Primary: keep apps grouped by directory (so the directory tree filter
        # shows contiguous groups). Secondary: the user's chosen sort key,
        # reversed if descending. Directory order is always APP_DIRS.
        _dir_order = {
            ("system", "app"): 0, ("system", "priv-app"): 1,
            ("system", "preinstall"): 2, ("product", "app"): 3,
            ("product", "priv-app"): 4, ("system_ext", "app"): 5,
            ("system_ext", "priv-app"): 6,
        }
        secondary = {
            "name": lambda a: a.name.lower(),
            "size": lambda a: a.size,
            "guard": lambda a: (
                0 if a.guard is GuardLevel.CORE
                else 1 if a.guard is GuardLevel.GUARDED
                else 2
            ),
            "fileCount": lambda a: a.file_count,
        }.get(self._sort_key, lambda a: a.name.lower())
        rev = bool(getattr(self, "_sort_desc", False))

        def sort_key(p):
            app = p[0]
            return (_dir_order.get((app.partition, app.privilege), 99),
                    secondary(app))
        paired = list(zip(self._apps, self._checked))
        paired.sort(key=sort_key)
        # Reverse within each directory group when descending (keeps the
        # directory grouping intact, only flips intra-group order).
        if rev:
            out = []
            i = 0
            while i < len(paired):
                j = i
                key0 = _dir_order.get(
                    (paired[i][0].partition, paired[i][0].privilege), 99)
                while j < len(paired) and _dir_order.get(
                        (paired[j][0].partition, paired[j][0].privilege), 99) == key0:
                    j += 1
                out.extend(paired[i:j][::-1])
                i = j
            paired = out
        self.beginResetModel()
        self._apps = [p[0] for p in paired]
        self._checked = [p[1] for p in paired]
        # build visible-row index map (respecting the section filter)
        self._visible = [
            i for i, a in enumerate(self._apps)
            if self._filter_section is None
            or _section_key(a) == self._filter_section
        ]
        self.endResetModel()

    def _real_row(self, visible_row: int) -> int:
        """Map a visible ListView row to the underlying app index."""
        return self._visible[visible_row]

    # ---- selection results ----

    def selected_apps(self) -> list[AppEntry]:
        return [a for a, c in zip(self._apps, self._checked) if c]

    def selected_app_names(self) -> list[str]:
        return [a.name for a in self.selected_apps()]

    def reclaim_total(self) -> int:
        return sum(a.size for a, c in zip(self._apps, self._checked) if c)

    def selected_count(self) -> int:
        return sum(1 for c in self._checked if c)

    # ---- QAbstractListModel API ----

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._visible)

    def roleNames(self):
        return _APP_ROLES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        i = self._real_row(index.row())
        if i < 0 or i >= len(self._apps):
            return None
        app = self._apps[i]
        if role == _NAME:
            return app.name
        if role == _PARTITION:
            return app.partition
        if role == _PRIVILEGE:
            return app.privilege
        if role == _IMAGEPATH:
            return app.image_path
        if role == _SIZE:
            return app.size
        if role == _FILECOUNT:
            return app.file_count
        if role == _GUARD:
            return _GUARD_STR[app.guard]
        if role == _CHECKED:
            return self._checked[i]
        if role == _GUARDREASON:
            return _guard_reason(app)
        if role == _SECTION:
            return _section_key(app)
        if role == _SECTIONLABEL:
            return _section_label(app)
        if role == Qt.ItemDataRole.ToolTipRole:
            return _guard_reason(app)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        app = self._apps[self._real_row(index.row())]
        if app.guard is GuardLevel.CORE:
            # Core: never checkable.
            return base
        if app.guard is GuardLevel.GUARDED and not self._risk_override:
            # Guarded without override: not checkable.
            return base
        return base | Qt.ItemFlag.ItemIsUserCheckable

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole:
            return False
        i = self._real_row(index.row())
        if i < 0 or i >= len(self._apps):
            return False
        app = self._apps[i]
        target = bool(value)
        # Enforce guard rules server-side regardless of what the view asked for.
        if app.guard is GuardLevel.CORE:
            # Always refuse; the view must reflect unchecked.
            self.dataChanged.emit(index, index, [_CHECKED])
            self.guardBlocked.emit(app.name, f"“{app.name}”是核心系统应用，不可删除。")
            return False
        if app.guard is GuardLevel.GUARDED and not self._risk_override:
            self.dataChanged.emit(index, index, [_CHECKED])
            self.guardBlocked.emit(
                app.name, f"“{app.name}”受保护。请勾选“风险覆盖”开关后再删除。")
            return False
        if self._checked[i] == target:
            return False
        self._checked[i] = target
        self.dataChanged.emit(index, index, [_CHECKED])
        return True

    def force_refresh_checked(self, row: int) -> None:
        """Tell the view to re-read the checked role (used to 'revert' an
        illegal view-side flip back to the model's truth)."""
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [_CHECKED])

    @Slot(int, bool)
    def setChecked(self, row: int, value: bool) -> None:
        """QML-facing toggle. Routes through setData() so guard rules apply."""
        self.setData(self.index(row), value, Qt.ItemDataRole.CheckStateRole)


# ---- Files (advanced) model -------------------------------------------------

_FILE_ROLES = {
    Qt.ItemDataRole.DisplayRole + 0x0100: b"path",
    Qt.ItemDataRole.DisplayRole + 0x0101: b"protected",
    Qt.ItemDataRole.DisplayRole + 0x0102: b"checked",
}

_F_PATH = Qt.ItemDataRole.DisplayRole + 0x0100
_F_PROTECTED = Qt.ItemDataRole.DisplayRole + 0x0101
_F_CHECKED = Qt.ItemDataRole.DisplayRole + 0x0102


class FileTreeModel(QAbstractListModel):
    """Flat list of directories in the extracted tree for the advanced view.

    Protected system paths are flagged and refuse selection (guard rule in
    the model, not the view).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._paths: list[str] = []
        self._protected: list[bool] = []
        self._checked: list[bool] = []
        self._protected_paths: list[str] = []

    def load(self, tree_root: str, protected_paths: list[str]) -> None:
        self.beginResetModel()
        self._protected_paths = list(protected_paths)
        self._paths = []
        self._protected = []
        self._checked = []
        for dirpath, _dirnames, _filenames in os.walk(tree_root):
            rel = "/" + os.path.relpath(dirpath, tree_root)
            rel = "/" if rel == "/." else rel
            prot = catalog.is_protected(rel, self._protected_paths)
            self._paths.append(rel)
            self._protected.append(prot)
            self._checked.append(False)
        self.endResetModel()

    def load_rows(self, rows: list, protected_paths: list[str]) -> None:
        """Populate from pre-walked rows (collected off the main thread).

        `rows` is a list of (relpath, protected) pairs.
        """
        self.beginResetModel()
        self._protected_paths = list(protected_paths)
        self._paths = [r[0] for r in rows]
        self._protected = [bool(r[1]) for r in rows]
        self._checked = [False] * len(rows)
        self.endResetModel()

    def selected_paths(self) -> list[str]:
        return [p for p, c in zip(self._paths, self._checked) if c]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._paths)

    def roleNames(self):
        return _FILE_ROLES

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        i = index.row()
        if i < 0 or i >= len(self._paths):
            return None
        if role == _F_PATH:
            return self._paths[i]
        if role == _F_PROTECTED:
            return self._protected[i]
        if role == _F_CHECKED:
            return self._checked[i]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self._protected[index.row()]:
            return base
        return base | Qt.ItemFlag.ItemIsUserCheckable

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole:
            return False
        i = index.row()
        if self._protected[i]:
            self.dataChanged.emit(index, index, [_F_CHECKED])
            return False
        target = bool(value)
        if self._checked[i] == target:
            return False
        self._checked[i] = target
        self.dataChanged.emit(index, index, [_F_CHECKED])
        return True

    @Slot(int, bool)
    def setChecked(self, row: int, value: bool) -> None:
        self.setData(self.index(row), value, Qt.ItemDataRole.CheckStateRole)


# ---- Big-file model (largest files across the tree) ------------------------

_BIG_ROLES = {
    Qt.ItemDataRole.DisplayRole + 0x0100: b"path",
    Qt.ItemDataRole.DisplayRole + 0x0101: b"size",
    Qt.ItemDataRole.DisplayRole + 0x0102: b"guard",   # "none"|"guarded"|"core"
    Qt.ItemDataRole.DisplayRole + 0x0103: b"checked",
}

_B_PATH = Qt.ItemDataRole.DisplayRole + 0x0100
_B_SIZE = Qt.ItemDataRole.DisplayRole + 0x0101
_B_GUARD = Qt.ItemDataRole.DisplayRole + 0x0102
_B_CHECKED = Qt.ItemDataRole.DisplayRole + 0x0103


class BigFileModel(QAbstractListModel):
    """Flat list of the largest files in the extracted tree.

    Shows path/size; each file carries a guard level ("none"|"guarded"|"core")
    inherited from the app it belongs to (by image_path prefix). Selection
    rules mirror the app catalog: core files are never deletable, guarded
    files are deletable only with risk-override on. This keeps the big-file
    view bound to the same "允许删除受保护应用" toggle as the app list — a
    big file under a guarded app can't be picked off here to bypass the guard.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._paths: list[str] = []
        self._sizes: list[int] = []
        self._guards: list[str] = []   # "none"|"guarded"|"core"
        self._checked: list[bool] = []
        self._risk_override: bool = False
        # image_path prefixes of apps selected in the app list; files under
        # these show as checked (will be deleted with the app).
        self._selected_app_prefixes: set[str] = set()

    def load_rows(self, rows: list) -> None:
        """Populate from pre-collected (relpath, size, guard) rows."""
        self.beginResetModel()
        self._paths = [r[0] for r in rows]
        self._sizes = [int(r[1]) for r in rows]
        self._guards = [str(r[2]) for r in rows]
        self._checked = [False] * len(rows)
        self.endResetModel()

    @Slot(bool)
    def set_risk_override(self, on: bool) -> None:
        """Apply the "允许删除受保护应用" toggle. Turning it off drops any
        guarded big-file selections (they are no longer deletable)."""
        if on == self._risk_override:
            return
        self._risk_override = on
        if not on and self._paths:
            changed = False
            for i, g in enumerate(self._guards):
                if g == "guarded" and self._checked[i]:
                    self._checked[i] = False
                    changed = True
            if self._paths:
                self.dataChanged.emit(self.index(0), self.index(len(self._paths) - 1),
                                      [_B_CHECKED, _B_GUARD])
            if changed:
                # selection shrank → reclaim total changed (Controller listens)
                self.dataChanged.emit(self.index(0), self.index(0), [_B_CHECKED])

    @Slot("QVariantList")
    def setSelectedAppPaths(self, app_paths) -> None:
        """Mark big files that fall under a selected app's directory.

        `app_paths` is a list of image_path prefixes (e.g. "/product/app/YouTube").
        Files whose path starts with one of these are reported as checked by
        the app selection (deleted with the app), even if not manually checked.
        """
        self._selected_app_prefixes = set(p.rstrip("/") for p in app_paths if p)
        if self._paths:
            self.dataChanged.emit(self.index(0), self.index(len(self._paths) - 1),
                                  [_B_CHECKED])

    def _covered_by_app(self, row: int) -> bool:
        p = self._paths[row]
        for prefix in self._selected_app_prefixes:
            if p == prefix or p.startswith(prefix + "/"):
                return True
        return False

    def selected_paths(self) -> list[str]:
        # only manually-checked files; app-covered files are deleted with the
        # app (their image_path is already in the app deletions), so don't
        # double-count them here.
        return [p for p, c in zip(self._paths, self._checked) if c]

    def selected_size(self) -> int:
        return sum(s for s, c in zip(self._sizes, self._checked) if c)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._paths)

    def roleNames(self):
        return _BIG_ROLES

    def _selectable(self, i: int) -> bool:
        g = self._guards[i]
        if g == "core":
            return False
        if g == "guarded" and not self._risk_override:
            return False
        return True

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        i = index.row()
        if i < 0 or i >= len(self._paths):
            return None
        if role == _B_PATH:
            return self._paths[i]
        if role == _B_SIZE:
            return self._sizes[i]
        if role == _B_GUARD:
            return self._guards[i]
        if role == _B_CHECKED:
            return self._checked[i] or self._covered_by_app(i)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self._selectable(index.row()):
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole:
            return False
        i = index.row()
        if not self._selectable(i):
            # refuse and bounce the view's checkbox back to the model's state
            self.dataChanged.emit(index, index, [_B_CHECKED])
            return False
        target = bool(value)
        if self._checked[i] == target:
            return False
        self._checked[i] = target
        self.dataChanged.emit(index, index, [_B_CHECKED])
        return True

    @Slot(int, bool)
    def setChecked(self, row: int, value: bool) -> None:
        self.setData(self.index(row), value, Qt.ItemDataRole.CheckStateRole)
