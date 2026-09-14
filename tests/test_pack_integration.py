"""Integration tests for the pack half (Tasks 8.2, 8.3, 8.4).

These exercise the root-free path: mke2fs -d build, e2fsck validation,
assert-no-footer, and debugfs inspection. The full unpack loop-mount (needs
root) is tested separately and skipped when root is unavailable.
"""

import json
import os
import shutil
import subprocess

import pytest

from systemimgkit import catalog, pack
from systemimgkit.errors import SizeCapExceededError, ValidationFailedError
from systemimgkit.workspace import Workspace

DEBUGFS = "debugfs"
MKE2FS = "mke2fs"


def _have(tool):
    return shutil.which(tool) is not None


needs_e2fsprogs = pytest.mark.skipif(
    not (_have(MKE2FS) and _have(DEBUGFS)),
    reason="e2fsprogs (mke2fs, debugfs) not installed",
)


def _make_fixture_tree(root):
    """A small Android-ish tree with one deletable app + one core app."""
    from pathlib import Path
    root = Path(root)
    app = root / "system" / "app" / "YouTube"
    app.mkdir(parents=True)
    (app / "base.apk").write_bytes(b"youtube-apk-payload" * 64)
    core = root / "product" / "priv-app" / "GmsCore"
    core.mkdir(parents=True)
    (core / "base.apk").write_bytes(b"gms-core-payload" * 64)
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "etc" / "hosts").write_text("127.0.0.1 localhost\n")
    # a symlink
    (root / "system" / "app" / "link").mkdir(parents=True)
    os.symlink("YouTube", root / "system" / "app" / "link" / "to_yt")


def _write_manifest(ws, block_count, entries=None):
    man = {
        "image_format": "raw-ext4",
        "original_image_size": block_count * 4096,
        "block_size": 4096,
        "block_count": block_count,
        "footer_stripped": True,
        "incomplete": False,
        "capture_notes": [],
        "entries": entries or [],
    }
    with open(ws.manifest, "w") as fh:
        json.dump(man, fh)


def _debugfs_ls(img, path):
    """Return the raw `debugfs ls` output for a path (for existence checks)."""
    res = subprocess.run([DEBUGFS, "-R", f"ls {path}", img],
                         capture_output=True, text=True)
    return res.stdout + res.stderr


@needs_e2fsprogs
def test_pack_builds_clean_footerless_image(tmp_path):
    ws = Workspace(root=str(tmp_path / "ws"))
    os.makedirs(ws.root, exist_ok=True)
    _make_fixture_tree(ws.tree)  # writes directly under ws.tree
    _write_manifest(ws, block_count=512)  # 2 MiB image, plenty for the tree
    out = str(tmp_path / "system_new.img")

    res = pack.pack(ws, out, deletions=["/system/app/YouTube"])

    assert os.path.isfile(res.output_image)
    assert os.path.getsize(res.output_image) == 512 * 4096
    assert os.path.exists(res.flash_script)
    # flash.sh must not reboot to fastboot or invoke adb (device enters fastboot manually).
    with open(res.flash_script) as fh:
        _flash_text = fh.read()
    assert "adb reboot fastboot" not in _flash_text
    # no `adb` invocation anywhere in the script (header or body)
    assert " adb " not in _flash_text and not _flash_text.lstrip().startswith("adb ")
    # the prerequisite line in the header must not advertise adb
    for _line in _flash_text.splitlines():
        if _line.startswith("# Prerequisites:"):
            assert "adb" not in _line, _line
    # Task 4.8: no AVB footer on the output.
    from systemimgkit import avb
    avb.assert_no_footer(res.output_image)  # would raise if footer present
    # The deleted app must be gone, the core app must remain.
    yt = _debugfs_ls(res.output_image, "/system/app")
    assert "YouTube" not in yt, yt
    gms = _debugfs_ls(res.output_image, "/product/priv-app")
    assert "GmsCore" in gms, gms


@needs_e2fsprogs
def test_pack_roundtrip_empty_deletions(tmp_path):
    """Task 8.3: round-trip with empty deletion set keeps all files."""
    ws = Workspace(root=str(tmp_path / "ws"))
    os.makedirs(ws.root, exist_ok=True)
    _make_fixture_tree(ws.tree)
    _write_manifest(ws, block_count=512)
    out = str(tmp_path / "system_new.img")

    res = pack.pack(ws, out, deletions=[])

    yt = _debugfs_ls(res.output_image, "/system/app")
    assert "YouTube" in yt
    gms = _debugfs_ls(res.output_image, "/product/priv-app")
    assert "GmsCore" in gms
    # hosts file preserved
    etc = _debugfs_ls(res.output_image, "/system/etc")
    assert "hosts" in etc


@needs_e2fsprogs
def test_pack_refuses_when_tree_exceeds_partition(tmp_path):
    """Task 4.2: refuse if the edited tree exceeds the original image size."""
    ws = Workspace(root=str(tmp_path / "ws"))
    os.makedirs(ws.root, exist_ok=True)
    _make_fixture_tree(ws.tree)
    # Add a payload larger than the tiny target so the byte-count guard trips.
    from pathlib import Path
    big = Path(ws.tree) / "system" / "big.bin"
    big.parent.mkdir(parents=True, exist_ok=True)
    big.write_bytes(b"\x00" * 8192)
    _write_manifest(ws, block_count=1)  # 4096-byte target < 8192-byte payload
    out = str(tmp_path / "system_new.img")
    with pytest.raises(SizeCapExceededError):
        pack.pack(ws, out, deletions=[])


@needs_e2fsprogs
def test_pack_clamps_when_target_larger_than_original(tmp_path):
    """pack-target-clamp 3.1: target_blocks > original_block_count no longer
    raises; it builds at original_block_count and reports the clamp via on_line."""
    ws = Workspace(root=str(tmp_path / "ws"))
    os.makedirs(ws.root, exist_ok=True)
    _make_fixture_tree(ws.tree)
    _write_manifest(ws, block_count=512)            # 2 MiB original
    out = str(tmp_path / "system_new.img")
    lines = []
    res = pack.pack(ws, out, deletions=[],
                    target_blocks=1024,             # larger than 512
                    on_line=lines.append)
    # No raise (reaching here proves it); builds at the original size.
    assert res.block_count == 512
    assert os.path.getsize(res.output_image) == 512 * 4096
    # on_line received the clamp info naming both block counts.
    clamp_lines = [l for l in lines if "按原镜像大小建镜像" in l]
    assert clamp_lines, lines
    assert "1,024" in clamp_lines[0] and "512" in clamp_lines[0]
    # The clamp is also recorded as a structured warning for CLI/JSON consumers.
    assert any("按原镜像大小建镜像" in w for w in res.warnings)


@needs_e2fsprogs
def test_pack_target_equal_to_original_builds_at_original(tmp_path):
    """pack-target-clamp 3.2: target == original builds at original (regression
    — unchanged from the prior fall-through, no info/warning emitted)."""
    ws = Workspace(root=str(tmp_path / "ws"))
    os.makedirs(ws.root, exist_ok=True)
    _make_fixture_tree(ws.tree)
    _write_manifest(ws, block_count=512)
    out = str(tmp_path / "system_new.img")
    lines = []
    res = pack.pack(ws, out, deletions=[],
                    target_blocks=512,
                    on_line=lines.append)
    assert res.block_count == 512
    assert os.path.getsize(res.output_image) == 512 * 4096
    # Equal case falls through silently — no clamp info, no warning.
    assert not any("按原镜像大小建镜像" in l for l in lines)
    assert not any("按原镜像大小建镜像" in w for w in res.warnings)


@needs_e2fsprogs
def test_pack_target_smaller_than_original_builds_at_target(tmp_path):
    """pack-target-clamp 3.3: 0 < target < original builds at target
    (regression, unchanged)."""
    ws = Workspace(root=str(tmp_path / "ws"))
    os.makedirs(ws.root, exist_ok=True)
    _make_fixture_tree(ws.tree)
    _write_manifest(ws, block_count=512)            # 2 MiB original
    out = str(tmp_path / "system_new.img")
    lines = []
    res = pack.pack(ws, out, deletions=[],
                    target_blocks=256,              # shrink to 1 MiB
                    on_line=lines.append)
    assert res.block_count == 256
    assert os.path.getsize(res.output_image) == 256 * 4096
    # Shrink path emits its own info line, not the clamp line.
    assert any("按目标大小建镜像" in l for l in lines)
    assert not any("按原镜像大小建镜像" in l for l in lines)


@needs_e2fsprogs
def test_pack_no_target_builds_at_original(tmp_path):
    """pack-target-clamp 3.4: target_blocks == 0 builds at original
    (regression, unchanged)."""
    ws = Workspace(root=str(tmp_path / "ws"))
    os.makedirs(ws.root, exist_ok=True)
    _make_fixture_tree(ws.tree)
    _write_manifest(ws, block_count=512)
    out = str(tmp_path / "system_new.img")
    res = pack.pack(ws, out, deletions=[], target_blocks=0)
    assert res.block_count == 512
    assert os.path.getsize(res.output_image) == 512 * 4096


def test_source_unchanged_after_strip(tmp_path):
    """Task 8.4: the source image is byte-identical before/after stripping."""
    from systemimgkit import avb
    import struct
    payload = b"\x00" * 8192
    blob = bytearray(64)
    blob[0:4] = b"AVBf"
    struct.pack_into(">Q", blob, 12, len(payload))
    src = tmp_path / "system.img"
    src.write_bytes(payload + bytes(blob))
    before = src.read_bytes()
    mtime = os.path.getmtime(src)
    dest = tmp_path / "work.img"
    avb.strip_footer(str(src), str(dest))
    assert src.read_bytes() == before
    assert os.path.getmtime(src) == mtime
