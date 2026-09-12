"""End-to-end unpack test on a real (small) ext4 image (Task 8.2 unpack half).

Builds a tiny ext4 image with mke2fs, appends an AVB footer, and runs the full
unpack. In an environment without usable root (pkexec/sudo unavailable or auth
denied), unpack falls back to the rootless debugfs path. This test verifies
that fallback end-to-end: the tree is extracted, the manifest is written and
marked incomplete, and the source image is byte-identical afterward.
"""

import os
import shutil
import struct
import subprocess

import pytest

from systemimgkit import unpack
from systemimgkit.workspace import Workspace

MKE2FS = "mke2fs"
DEBUGFS = "debugfs"


def _have(tool):
    return shutil.which(tool) is not None


needs_e2fsprogs = pytest.mark.skipif(
    not (_have(MKE2FS) and _have(DEBUGFS)),
    reason="e2fsprogs (mke2fs, debugfs) not installed",
)


def _make_ext4_with_footer(tmp_path, block_count=512):
    from pathlib import Path
    tree = Path(tmp_path) / "src_tree"
    (tree / "system" / "app" / "Demo").mkdir(parents=True)
    (tree / "system" / "app" / "Demo" / "base.apk").write_bytes(b"demo" * 64)
    (tree / "etc").mkdir(parents=True)
    (tree / "etc" / "hosts").write_text("127.0.0.1 localhost\n")

    img = Path(tmp_path) / "system.img"
    # Build ext4 from the tree.
    subprocess.run(
        [MKE2FS, "-t", "ext4", "-b", "4096", "-L", "/", "-d", str(tree),
         str(img), str(block_count)],
        check=True, capture_output=True,
    )
    original_size = os.path.getsize(img)
    # Append a synthetic AVB footer.
    footer = bytearray(64)
    footer[0:4] = b"AVBf"
    struct.pack_into(">I", footer, 4, 1)
    struct.pack_into(">I", footer, 8, 0)
    struct.pack_into(">Q", footer, 12, original_size)
    with open(img, "ab") as fh:
        fh.write(bytes(footer))
    return img, original_size


@needs_e2fsprogs
def test_unpack_rootless_e2e(tmp_path):
    img, original_size = _make_ext4_with_footer(tmp_path)
    src_bytes = img.read_bytes()
    ws_dir = str(tmp_path / "ws")

    res = unpack.unpack(str(img), ws_dir, allow_rootless=True, on_line=lambda _l: None)

    ws = Workspace(root=ws_dir)
    # The tree was extracted (rootless debugfs rdump).
    assert os.path.isdir(ws.tree), "tree not extracted"
    demo = os.path.join(ws.tree, "system", "app", "Demo", "base.apk")
    assert os.path.isfile(demo), "Demo/base.apk not extracted"
    # The manifest exists and is marked incomplete (rootless path).
    assert os.path.isfile(ws.manifest)
    from systemimgkit import manifest as M
    man = M.Manifest.load(ws.manifest)
    assert man.incomplete is True
    assert man.footer_stripped is True
    assert man.original_image_size == original_size
    # Task 8.4: source image byte-identical and untouched.
    assert img.read_bytes() == src_bytes
