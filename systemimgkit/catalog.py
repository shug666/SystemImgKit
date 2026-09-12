"""Catalog: enumerate pre-installed apps, enforce the guard-list, record deletions.

Tasks 3.1 (walk the six app dirs), 3.3 (guard enforcement + risk override),
3.4 (protected-path guarding), 3.5 (search/filter), 3.6 (deletion-set record).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

import yaml

from .errors import GuardViolationError
from .workspace import Workspace

# The app directories, grouped by partition + privilege. The standard AOSP six
# plus ZUI's /system/preinstall (where this OEM stashes most bundled/bloat
# apps: Instagram, CapCut, Adobe LightRoom, Opera, YouTubeKids, …).
APP_DIRS: list[tuple[str, str, str]] = [
    # (partition, privilege, image path)
    ("system", "app", "/system/app"),
    ("system", "priv-app", "/system/priv-app"),
    ("system", "preinstall", "/system/preinstall"),  # ZUI bundled apps
    ("product", "app", "/product/app"),
    ("product", "priv-app", "/product/priv-app"),
    ("system_ext", "app", "/system_ext/app"),
    ("system_ext", "priv-app", "/system_ext/priv-app"),
]

_GUARDLIST_FILE = os.path.join(os.path.dirname(__file__), "data", "guardlist.yaml")


class GuardLevel(Enum):
    NONE = "none"           # freely deletable
    GUARDED = "guarded"     # deletable only with risk override
    CORE = "core"           # never deletable


@dataclass(frozen=True)
class AppEntry:
    name: str               # app directory name, e.g. "YouTube"
    partition: str          # system | product | system_ext
    privilege: str          # app | priv-app
    image_path: str         # e.g. /product/app/YouTube
    tree_path: str          # absolute path within the extracted tree
    size: int               # recursive size in bytes
    file_count: int
    guard: GuardLevel


@dataclass
class Catalog:
    apps: list[AppEntry] = field(default_factory=list)
    protected_paths: list[str] = field(default_factory=list)

    def filter(self, *, query: str | None = None, partition: str | None = None,
               privilege: str | None = None) -> list[AppEntry]:
        out = self.apps
        if partition:
            out = [a for a in out if a.partition == partition]
        if privilege:
            out = [a for a in out if a.privilege == privilege]
        if query:
            q = query.lower()
            out = [a for a in out if q in a.name.lower()]
        return out


@dataclass
class GuardList:
    version: int
    core: set[str]
    guarded: set[str]
    protected_paths: list[str]

    @classmethod
    def default(cls) -> "GuardList":
        return cls.load(_GUARDLIST_FILE)

    @classmethod
    def load(cls, path: str) -> "GuardList":
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        core = set(data.get("generic", {}).get("core", []))
        guarded = set(data.get("generic", {}).get("guarded", []))
        protected = list(data.get("generic", {}).get("protected_paths", []))
        # Apply ZUI overlay (adds to core/guarded).
        zui = data.get("zui", {})
        core |= set(zui.get("core", []))
        guarded |= set(zui.get("guarded", []))
        return cls(
            version=data.get("version", 1),
            core=core,
            guarded=guarded,
            protected_paths=protected,
        )

    def level(self, name: str) -> GuardLevel:
        if name in self.core:
            return GuardLevel.CORE
        if name in self.guarded:
            return GuardLevel.GUARDED
        return GuardLevel.NONE


def _du(path: str) -> tuple[int, int]:
    """Recursive size + file count of a directory tree."""
    total = 0
    count = 0
    for dirpath, _, filenames in os.walk(path):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                total += os.lstat(fp).st_size
                count += 1
            except OSError:
                pass
    return total, count


def build_catalog(tree_root: str, guard: GuardList | None = None) -> Catalog:
    """Walk the six app directories under the extracted tree (Task 3.1)."""
    guard = guard or GuardList.default()
    apps: list[AppEntry] = []
    for partition, privilege, img_path in APP_DIRS:
        tree_dir = os.path.join(tree_root, img_path.lstrip("/"))
        if not os.path.isdir(tree_dir):
            continue
        for name in sorted(os.listdir(tree_dir)):
            app_path = os.path.join(tree_dir, name)
            if not os.path.isdir(app_path):
                continue
            size, fcount = _du(app_path)
            apps.append(AppEntry(
                name=name,
                partition=partition,
                privilege=privilege,
                image_path=img_path + "/" + name,
                tree_path=app_path,
                size=size,
                file_count=fcount,
                guard=guard.level(name),
            ))
    return Catalog(apps=apps, protected_paths=list(guard.protected_paths))


# --- Deletion-set selection + enforcement (Tasks 3.3, 3.4, 3.6) -------------

def is_protected(path: str, protected_paths: Iterable[str]) -> bool:
    """Return True if `path` (an image-relative path like /system/…) is protected."""
    p = path.rstrip("/")
    for prot in protected_paths:
        prot = prot.rstrip("/")
        if p == prot or p.startswith(prot + "/"):
            return True
    return False


def select_deletions(
    catalog: Catalog,
    chosen_app_names: Iterable[str],
    *,
    chosen_file_paths: Iterable[str] = (),
    risk_override: bool = False,
    override_log: list[str] | None = None,
) -> list[str]:
    """Validate and assemble the ordered deletion set (image-relative paths).

    `chosen_app_names`: app directory names selected from the catalog.
    `chosen_file_paths`: arbitrary image-relative paths from the Files view.

    Raises GuardViolationError if a core entry or protected path is selected.
    Records overrides for guarded entries in `override_log`.
    """
    guard = GuardList.default()
    name_to_entry = {a.name: a for a in catalog.apps}
    deletions: list[str] = []
    seen: set[str] = set()

    for name in chosen_app_names:
        entry = name_to_entry.get(name)
        if entry is None:
            raise GuardViolationError(f"unknown app selected: {name}")
        if entry.guard is GuardLevel.CORE:
            raise GuardViolationError(
                f"'{name}' is a core system app and cannot be removed "
                f"(removal would brick the OS)."
            )
        if entry.guard is GuardLevel.GUARDED and not risk_override:
            raise GuardViolationError(
                f"'{name}' is guarded; enable the risk-override toggle to "
                f"remove it (this will be logged)."
            )
        if entry.guard is GuardLevel.GUARDED and risk_override and override_log is not None:
            override_log.append(f"OVERRIDE: removed guarded app '{name}' "
                                f"({entry.image_path}, {entry.size} bytes)")
        if entry.image_path not in seen:
            deletions.append(entry.image_path)
            seen.add(entry.image_path)

    for fpath in chosen_file_paths:
        fpath = fpath if fpath.startswith("/") else "/" + fpath
        if is_protected(fpath, catalog.protected_paths):
            raise GuardViolationError(
                f"'{fpath}' is a protected system path and cannot be removed."
            )
        if fpath not in seen:
            deletions.append(fpath)
            seen.add(fpath)

    return deletions


def save_deletions(workspace: Workspace, deletions: list[str]) -> str:
    """Task 3.6: persist the deletion set for the pack stage."""
    with open(workspace.deletions, "w", encoding="utf-8") as fh:
        for p in deletions:
            fh.write(p + "\n")
    return workspace.deletions


def load_deletions(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]
