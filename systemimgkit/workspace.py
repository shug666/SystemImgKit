"""Workspace management and free-space precheck.

Task 1.4: a configurable workspace directory plus a precheck that ensures
enough free space exists for the unpack step (source size + headroom) before
any large file is created.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from .errors import InsufficientSpaceError

# Extra headroom beyond the source size: enough for the working copy *and* the
# extracted tree to coexist briefly. The working copy (footerless image) is
# ~source size; the tree is ~source size; allow a 10% margin on top.
DEFAULT_HEADROOM_FACTOR = 1.1
MIN_HEADROOM_BYTES = 256 * 1024 * 1024  # 256 MiB floor


@dataclass
class Workspace:
    root: str  # the workspace directory

    @property
    def work_image(self) -> str:
        """The footerless truncated copy of the source image."""
        return os.path.join(self.root, "system.work.img")

    @property
    def orig_backup(self) -> str:
        """Marker path for the original-image size record (not a full copy)."""
        return os.path.join(self.root, "source.size")

    @property
    def tree(self) -> str:
        """The extracted file tree root."""
        return os.path.join(self.root, "tree")

    @property
    def manifest(self) -> str:
        """The metadata manifest (JSON)."""
        return os.path.join(self.root, "manifest.json")

    @property
    def deletions(self) -> str:
        """The recorded deletion set."""
        return os.path.join(self.root, "deletions.txt")


def create_workspace(path: str, exist_ok: bool = True) -> Workspace:
    """Create the workspace directory tree."""
    os.makedirs(path, exist_ok=exist_ok)
    ws = Workspace(root=path)
    return ws


def free_space_bytes(path: str) -> int:
    """Free bytes available on the filesystem holding `path`."""
    return shutil.disk_usage(path).free


def required_space(source_size: int, headroom_factor: float = DEFAULT_HEADROOM_FACTOR) -> int:
    """Bytes of free space required to unpack `source_size` bytes."""
    # working copy (~source) + extracted tree (~source), times headroom factor.
    base = source_size * 2
    headroom = max(int(base * (headroom_factor - 1.0)), MIN_HEADROOM_BYTES)
    return base + headroom


def precheck(workspace_dir: str, source_size: int, headroom_factor: float = DEFAULT_HEADROOM_FACTOR) -> int:
    """Verify free space; raise InsufficientSpaceError if insufficient.

    Returns the number of bytes that will be needed.
    """
    need = required_space(source_size, headroom_factor)
    # Ensure the parent exists so disk_usage resolves the right filesystem.
    parent = workspace_dir if os.path.exists(workspace_dir) else os.path.dirname(
        os.path.abspath(workspace_dir)
    ) or "/"
    have = free_space_bytes(parent)
    if have < need:
        raise InsufficientSpaceError(
            f"Need {need:,} bytes of free space in '{parent}' but only "
            f"{have:,} bytes are available (short by {need - have:,} bytes)."
        )
    return need
