"""Metadata manifest capture and (de)serialization.

Task 2.4: a JSON manifest recording, for every file in the extracted image
tree, the Android filesystem semantics that `mke2fs -d` does NOT store and
that must be re-applied after rebuilding: uid, gid, mode, mtime, hardlinks,
SELinux contexts (security.selinux), and capability bits (security.capability).

The manifest is captured by walking the *mounted* image (so original uids are
preserved), never the extracted tree (whose ownership may have been remapped).
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field, asdict
from typing import Any

SELINUX_XATTR = "security.selinux"
CAPABILITY_XATTR = "security.capability"


@dataclass
class FileEntry:
    relpath: str          # POSIX-style path relative to image root, e.g. "/system/app/Foo/base.apk"
    type: str             # "file" | "dir" | "symlink"
    mode: int             # st_mode permission bits (e.g. 0o755)
    uid: int
    gid: int
    mtime: float          # seconds since epoch (float)
    size: int             # file size in bytes (0 for dirs/symlinks)
    linktarget: str | None = None        # symlink target (for type=="symlink")
    hardlink_to: str | None = None       # relpath of the first inode sharing this st_ino
    selinux: str | None = None           # security.selinux context, or None
    capabilities: str | None = None       # security.capability xattr as hex string, or None


@dataclass
class Manifest:
    image_format: str = "raw-ext4"
    original_image_size: int = 0
    block_size: int = 4096
    block_count: int = 0
    footer_stripped: bool = False
    incomplete: bool = False            # True when captured via rootless fallback
    capture_notes: list[str] = field(default_factory=list)
    entries: list[FileEntry] = field(default_factory=list)
    # ext4 superblock geometry probed from the source image (for shared_blocks
    # rebuild): the feature list and the original inode count.
    features: list[str] = field(default_factory=list)
    inode_count: int = 0

    @property
    def has_shared_blocks(self) -> bool:
        return "shared_blocks" in (self.features or [])

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["entries"] = [asdict(e) for e in self.entries]
        return d

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=1, ensure_ascii=False)
            fh.write("\n")

    @classmethod
    def load(cls, path: str) -> "Manifest":
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        entries = [FileEntry(**e) for e in d.pop("entries", [])]
        return cls(entries=entries, **d)


def _getxattr(path: str, name: str) -> str | None:
    try:
        # follow_symlinks=False: read the xattr on the file/symlink itself,
        # not the symlink target. SELinux contexts live on symlinks too (e.g.
        # /init is a symlink with context u:object_r:init_exec:s0), and
        # following would resolve to the target path which may not exist.
        val = os.getxattr(path, name, follow_symlinks=False)
    except OSError:
        return None
    if name == SELINUX_XATTR:
        # SELinux contexts are NUL-terminated UTF-8 on disk.
        return val.split(b"\x00", 1)[0].decode("utf-8", "replace")
    return val.hex()  # capabilities: store raw bytes as hex


def capture_manifest(
    root: str,
    *,
    image_format: str = "raw-ext4",
    original_image_size: int = 0,
    block_size: int = 4096,
    block_count: int = 0,
    footer_stripped: bool = False,
    incomplete: bool = False,
    capture_notes: list[str] | None = None,
    features: list[str] | None = None,
    inode_count: int = 0,
) -> Manifest:
    """Walk a mounted image root and capture a full metadata manifest.

    `root` is the mount point (or extracted tree). Returns a Manifest.
    """
    notes = list(capture_notes or [])
    entries: list[FileEntry] = []
    inode_to_path: dict[int, str] = {}

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # The image root maps to "/" in relpath.
        rel_dir = _to_relpath(root, dirpath)
        # Emit the directory entry itself (skip the root "." — handled below).
        if rel_dir != "/":
            st = os.lstat(dirpath)
            _add_entry(entries, inode_to_path, rel_dir, st, root, dirpath, is_dir=True)
        # Emit each child (files, symlinks, subdirs as children of their parent).
        for name in sorted(dirnames + filenames):
            child = os.path.join(dirpath, name)
            rel_child = _to_relpath(root, child)
            try:
                st = os.lstat(child)
            except OSError:
                notes.append(f"lstat failed: {rel_child}")
                continue
            _add_entry(entries, inode_to_path, rel_child, st, root, child, is_dir=False)

    # Ensure the root entry exists.
    if not any(e.relpath == "/" for e in entries):
        try:
            st = os.lstat(root)
            entries.insert(0, FileEntry(
                relpath="/", type="dir", mode=stat.S_IMODE(st.st_mode),
                uid=st.st_uid, gid=st.st_gid, mtime=st.st_mtime, size=0,
            ))
        except OSError:
            pass

    return Manifest(
        image_format=image_format,
        original_image_size=original_image_size,
        block_size=block_size,
        block_count=block_count,
        footer_stripped=footer_stripped,
        incomplete=incomplete,
        capture_notes=notes,
        entries=entries,
        features=list(features or []),
        inode_count=inode_count,
    )


def _to_relpath(root: str, abspath: str) -> str:
    rel = os.path.relpath(abspath, root)
    if rel == ".":
        return "/"
    return "/" + rel.replace(os.sep, "/")


def _add_entry(entries, inode_to_path, relpath, st, root, abspath, is_dir):
    # Determine type.
    if stat.S_ISDIR(st.st_mode):
        ftype = "dir"
    elif stat.S_ISLNK(st.st_mode):
        ftype = "symlink"
    else:
        ftype = "file"

    linktarget = None
    if ftype == "symlink":
        try:
            linktarget = os.readlink(abspath)
        except OSError:
            linktarget = None

    hardlink_to = None
    # Only regular files (and possibly dirs) can be hardlinked; track inodes.
    if st.st_nlink > 1 and ftype == "file":
        if st.st_ino in inode_to_path:
            hardlink_to = inode_to_path[st.st_ino]
        else:
            inode_to_path[st.st_ino] = relpath

    selinux = _getxattr(abspath, SELINUX_XATTR)
    capabilities = _getxattr(abspath, CAPABILITY_XATTR) if ftype == "file" else None

    entries.append(FileEntry(
        relpath=relpath,
        type=ftype,
        mode=stat.S_IMODE(st.st_mode),
        uid=st.st_uid,
        gid=st.st_gid,
        mtime=st.st_mtime,
        size=st.st_size if ftype == "file" else 0,
        linktarget=linktarget,
        hardlink_to=hardlink_to,
        selinux=selinux,
        capabilities=capabilities,
    ))
