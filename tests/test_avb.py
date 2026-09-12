"""Unit tests: AVB footer parse/strip/restore + assert_no_footer (Task 8.1)."""

import os
import struct

from systemimgkit import avb
from systemimgkit.errors import AvbFooterError

FOOTER_MAGIC = b"AVBf"


def _make_footer(original_image_size: int, vbmeta_image_size: int = 0) -> bytes:
    blob = bytearray(64)
    blob[0:4] = FOOTER_MAGIC
    struct.pack_into(">I", blob, 4, 1)   # version_major
    struct.pack_into(">I", blob, 8, 0)   # version_minor
    struct.pack_into(">Q", blob, 12, original_image_size)
    struct.pack_into(">Q", blob, 20, vbmeta_image_size)
    return bytes(blob)


def test_parse_footer_big_endian():
    footer = _make_footer(original_image_size=11412365312, vbmeta_image_size=11593170944)
    parsed = avb.parse_footer(footer)
    assert parsed.version_major == 1
    assert parsed.version_minor == 0
    assert parsed.original_image_size == 11412365312
    assert parsed.vbmeta_image_size == 11593170944


def test_parse_footer_bad_magic():
    import pytest
    bad = bytearray(_make_footer(1024))
    bad[0:4] = b"XXXX"
    with pytest.raises(AvbFooterError):
        avb.parse_footer(bytes(bad))


def test_strip_footer_truncates_and_preserves_source(tmp_path):
    payload = b"\x00" * 4096 + b"hello-ext4"
    orig_size = len(payload)
    footer = _make_footer(original_image_size=orig_size)
    src = tmp_path / "src.img"
    src.write_bytes(payload + footer)
    src_bytes = src.read_bytes()
    src_mtime = os.path.getmtime(src)

    dest = tmp_path / "work.img"
    stripped, size = avb.strip_footer(str(src), str(dest))
    assert stripped is True
    assert size == orig_size
    assert dest.read_bytes() == payload  # footer removed
    # Source untouched (Task 8.4 invariant):
    assert src.read_bytes() == src_bytes
    assert os.path.getmtime(src) == src_mtime


def test_strip_footer_no_footer_copies_verbatim(tmp_path):
    payload = b"\x00" * 4096 + b"noinfooter"
    src = tmp_path / "src.img"
    src.write_bytes(payload)
    dest = tmp_path / "work.img"
    stripped, size = avb.strip_footer(str(src), str(dest))
    assert stripped is False
    assert size == len(payload)
    assert dest.read_bytes() == payload


def test_assert_no_footer_passes_without_footer(tmp_path):
    p = tmp_path / "out.img"
    p.write_bytes(b"\x00" * 4096)
    avb.assert_no_footer(str(p))  # must not raise


def test_assert_no_footer_raises_with_footer(tmp_path):
    import pytest
    p = tmp_path / "out.img"
    p.write_bytes(b"\x00" * 4096 + _make_footer(4096))
    with pytest.raises(AvbFooterError):
        avb.assert_no_footer(str(p))


def test_restore_footer_roundtrip(tmp_path):
    payload = b"\x00" * 4096 + b"data"
    orig_size = len(payload)
    footer = avb.parse_footer(_make_footer(orig_size))
    p = tmp_path / "img.img"
    p.write_bytes(payload)
    avb.restore_footer(str(p), footer)
    assert p.read_bytes() == payload + _make_footer(orig_size)
