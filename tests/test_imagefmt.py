"""Unit tests: image format detection (Task 8.1)."""

import struct

from systemimgkit import imagefmt


def test_detect_raw_ext4(tmp_path):
    p = tmp_path / "img.bin"
    data = bytearray(2048)
    # ext4 superblock magic 0xEF53 at offset 0x438, little-endian.
    struct.pack_into("<H", data, 0x438, 0xEF53)
    p.write_bytes(data)
    fmt, footer = imagefmt.ensure_supported(str(p))
    assert fmt is imagefmt.ImageFormat.RAW_EXT4
    assert footer is imagefmt.AvbFooterPresence.ABSENT


def test_detect_ext4_with_avb_footer(tmp_path):
    p = tmp_path / "img.bin"
    data = bytearray(2048)
    struct.pack_into("<H", data, 0x438, 0xEF53)
    data += b"\x00" * 64
    # write AVBf footer at the end
    blob = bytearray(data)
    blob[-64:-60] = b"AVBf"
    p.write_bytes(bytes(blob))
    fmt, footer = imagefmt.ensure_supported(str(p))
    assert fmt is imagefmt.ImageFormat.RAW_EXT4
    assert footer is imagefmt.AvbFooterPresence.PRESENT


def test_detect_sparse_rejected(tmp_path):
    import pytest
    from systemimgkit.errors import UnsupportedImageError
    p = tmp_path / "sparse.img"
    data = bytearray(64)
    struct.pack_into("<I", data, 0, 0xED26)  # android sparse magic
    p.write_bytes(data)
    with pytest.raises(UnsupportedImageError):
        imagefmt.ensure_supported(str(p))


def test_detect_erofs_rejected(tmp_path):
    import pytest
    from systemimgkit.errors import UnsupportedImageError
    p = tmp_path / "erofs.img"
    data = bytearray(2048)
    struct.pack_into("<I", data, 0x400, 0xE0F5E252)  # EROFS magic
    p.write_bytes(data)
    with pytest.raises(UnsupportedImageError):
        imagefmt.ensure_supported(str(p))
