"""Image format detection.

Task 2.1: identify whether the input system.img is raw ext4, sparse, or EROFS,
and detect an appended AVB footer. v1 supports raw ext4 only.
"""

from __future__ import annotations

import enum
import os
import struct

from .errors import UnsupportedImageError

# ext4 superblock magic 0xEF53 lives at byte offset 1080 (0x438) within the
# 1024-byte-bootsector + superblock layout.
EXT4_MAGIC_OFFSET = 0x438
EXT4_MAGIC = 0xEF53

# Android sparse image magic 0xED26 (little-endian: 26 ed).
SPARSE_MAGIC = 0xED26

# EROFS superblock magic "ER0S" / 0xE0F5E252? EROFS uses magic 0xE0F5E252 at
# offset 1024 (0x400). We detect via the ASCII "E0FS"? Actually EROFS magic is
# EROFS_SUPER_MAGIC_V1. We detect the well-known EROFS magic 0xE0F5E252 at 0x400.
EROFS_MAGIC_OFFSET = 0x400
EROFS_MAGIC = 0xE0F5E252  # stored little-endian on disk

# AVB footer lives in the last 64 bytes; magic "AVBf" = 0x41564266.
AVB_FOOTER_SIZE = 64
AVB_FOOTER_MAGIC = b"AVBf"


class ImageFormat(enum.Enum):
    RAW_EXT4 = "raw-ext4"
    SPARSE = "sparse"
    EROFS = "erofs"
    UNKNOWN = "unknown"


@enum.unique
class AvbFooterPresence(enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"


def _read_at(fh, offset: int, length: int) -> bytes:
    fh.seek(offset)
    return fh.read(length)


def detect_format(path: str) -> ImageFormat:
    """Detect the image container format. Reads only the first 2 KiB."""
    with open(path, "rb") as fh:
        # ext4 superblock magic
        data = _read_at(fh, EXT4_MAGIC_OFFSET, 2)
        if len(data) == 2 and struct.unpack("<H", data)[0] == EXT4_MAGIC:
            return ImageFormat.RAW_EXT4
        # sparse magic is at offset 0
        fh.seek(0)
        data = fh.read(4)
        if len(data) == 4 and struct.unpack("<I", data)[0] == SPARSE_MAGIC:
            return ImageFormat.SPARSE
        # EROFS magic at offset 0x400
        data = _read_at(fh, EROFS_MAGIC_OFFSET, 4)
        if len(data) == 4 and struct.unpack("<I", data)[0] == EROFS_MAGIC:
            return ImageFormat.EROFS
    return ImageFormat.UNKNOWN


def detect_avb_footer(path: str) -> AvbFooterPresence:
    """Return whether the file ends with an AVB footer."""
    size = os.path.getsize(path)
    if size < AVB_FOOTER_SIZE:
        return AvbFooterPresence.ABSENT
    with open(path, "rb") as fh:
        fh.seek(-AVB_FOOTER_SIZE, os.SEEK_END)
        footer = fh.read(AVB_FOOTER_SIZE)
    if footer[:4] == AVB_FOOTER_MAGIC:
        return AvbFooterPresence.PRESENT
    return AvbFooterPresence.ABSENT


def ensure_supported(path: str) -> tuple[ImageFormat, AvbFooterPresence]:
    """Validate that the image is a supported format for v1 (raw ext4).

    Raises UnsupportedImageError for sparse/EROFS/unknown. Returns the
    (format, footer presence) tuple on success.
    """
    fmt = detect_format(path)
    if fmt != ImageFormat.RAW_EXT4:
        raise UnsupportedImageError(
            f"Unsupported image format '{fmt.value}'. v1 supports raw ext4 "
            f"only; convert sparse images with simg2img first, and EROFS is "
            f"not supported yet."
        )
    footer = detect_avb_footer(path)
    return fmt, footer
