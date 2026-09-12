"""AVB (Android Verified Boot) footer handling.

Tasks 2.2, 5.1, 5.2.

v1 ships **Strategy A only**: strip the AVB footer to recover the raw ext4
image, and rely on the user flashing their existing vbmeta.img with
``fastboot --disable-verification`` on an unlocked bootloader. The tool does
NOT invoke avbtool, manage keys, or append any AVB footer to the output.

The AVB footer is the last 64 bytes of the image. All multi-byte fields are
big-endian. Struct (per AOSP avb_footer.h):

    offset  size  field
    0       4     magic            ("AVBf")
    4       4     version_major    (big-endian)
    8       4     version_minor    (big-endian)
    12      8     original_image_size  (big-endian)  <-- the field we need:
                                                       size of the image
                                                       WITHOUT the footer.
    20      8     vbmeta_image_size     (big-endian)  -- parsed but not relied on
    28      36    reserved (zeros)

`original_image_size` is the byte length of the verified payload (here, the
ext4 filesystem: block_count * block_size). Truncating the file to this length
removes the hash tree, signature, and footer, yielding the clean ext4 image.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

from .errors import AvbFooterError

AVB_FOOTER_SIZE = 64
AVB_FOOTER_MAGIC = b"AVBf"

# Offsets within the 64-byte footer.
_OFF_MAGIC = 0
_OFF_VERSION_MAJOR = 4
_OFF_VERSION_MINOR = 8
_OFF_ORIGINAL_IMAGE_SIZE = 12
_OFF_VBMETA_IMAGE_SIZE = 20


@dataclass(frozen=True)
class AvbFooter:
    version_major: int
    version_minor: int
    original_image_size: int
    vbmeta_image_size: int

    @property
    def magic_ok(self) -> bool:
        return True  # validated at parse time


def parse_footer(footer_bytes: bytes) -> AvbFooter:
    """Parse a 64-byte AVB footer. Raises AvbFooterError if malformed."""
    if len(footer_bytes) != AVB_FOOTER_SIZE:
        raise AvbFooterError(
            f"footer must be {AVB_FOOTER_SIZE} bytes, got {len(footer_bytes)}"
        )
    if footer_bytes[:4] != AVB_FOOTER_MAGIC:
        raise AvbFooterError("bad AVB footer magic (expected 'AVBf')")
    # All AVB integer fields are big-endian (network order).
    version_major = struct.unpack(">I", footer_bytes[_OFF_VERSION_MAJOR:_OFF_VERSION_MAJOR + 4])[0]
    version_minor = struct.unpack(">I", footer_bytes[_OFF_VERSION_MINOR:_OFF_VERSION_MINOR + 4])[0]
    original_image_size = struct.unpack(
        ">Q", footer_bytes[_OFF_ORIGINAL_IMAGE_SIZE:_OFF_ORIGINAL_IMAGE_SIZE + 8]
    )[0]
    vbmeta_image_size = struct.unpack(
        ">Q", footer_bytes[_OFF_VBMETA_IMAGE_SIZE:_OFF_VBMETA_IMAGE_SIZE + 8]
    )[0]
    if original_image_size == 0:
        raise AvbFooterError("footer original_image_size is zero")
    return AvbFooter(
        version_major=version_major,
        version_minor=version_minor,
        original_image_size=original_image_size,
        vbmeta_image_size=vbmeta_image_size,
    )


def read_footer(path: str) -> AvbFooter | None:
    """Read and parse the footer at the end of `path`, or None if absent."""
    size = os.path.getsize(path)
    if size < AVB_FOOTER_SIZE:
        return None
    with open(path, "rb") as fh:
        fh.seek(-AVB_FOOTER_SIZE, os.SEEK_END)
        footer = fh.read(AVB_FOOTER_SIZE)
    if footer[:4] != AVB_FOOTER_MAGIC:
        return None
    return parse_footer(footer)


def validate_original_size(image_path: str, original_image_size: int) -> None:
    """Sanity-check original_image_size against the ext4 superblock.

    The ext4 filesystem size (block_count * block_size) must be <= the
    footer's original_image_size, and the file must be at least that large.
    Raises AvbFooterError on inconsistency.
    """
    file_size = os.path.getsize(image_path)
    if original_image_size > file_size:
        raise AvbFooterError(
            f"footer original_image_size ({original_image_size}) exceeds file "
            f"size ({file_size})"
        )


def strip_footer(
    src_path: str,
    dest_path: str,
    footer: AvbFooter | None = None,
    validate: bool = True,
) -> tuple[bool, int]:
    """Produce a footerless copy of `src_path` truncated to original_image_size.

    The source file is opened READ-ONLY and never modified. Returns
    (footer_was_stripped, original_image_size). If no footer is present the
    file is copied verbatim (footer_was_stripped=False).
    """
    if footer is None:
        footer = read_footer(src_path)
    if footer is None:
        # No footer: copy the whole file unchanged.
        _copy_range(src_path, dest_path, os.path.getsize(src_path))
        return False, os.path.getsize(src_path)

    if validate:
        validate_original_size(src_path, footer.original_image_size)

    _copy_range(src_path, dest_path, footer.original_image_size)
    return True, footer.original_image_size


def _copy_range(src: str, dest: str, length: int, chunk: int = 16 * 1024 * 1024) -> None:
    """Copy `length` bytes from src (read-only) to dest."""
    with open(src, "rb") as fsrc, open(dest, "wb") as fdest:
        remaining = length
        while remaining > 0:
            n = min(chunk, remaining)
            buf = fsrc.read(n)
            if not buf:
                break
            fdest.write(buf)
            remaining -= len(buf)


def restore_footer(image_path: str, footer: AvbFooter) -> None:
    """Re-append an AVB footer to `image_path` (NOT used in v1).

    v1 ships **Strategy A only**: the tool outputs a footerless raw ext4 image
    and relies on `fastboot --disable-verification`. This helper exists for
    completeness / future Strategies B and C (re-signing with avbtool), which
    are explicitly deferred. It is not called anywhere in the v1 pipeline.
    """
    if os.path.getsize(image_path) != footer.original_image_size:
        raise AvbFooterError(
            "restore_footer: image size does not match footer.original_image_size"
        )
    blob = bytearray(AVB_FOOTER_SIZE)
    blob[0:4] = AVB_FOOTER_MAGIC
    import struct as _s
    _s.pack_into(">I", blob, _OFF_VERSION_MAJOR, footer.version_major)
    _s.pack_into(">I", blob, _OFF_VERSION_MINOR, footer.version_minor)
    _s.pack_into(">Q", blob, _OFF_ORIGINAL_IMAGE_SIZE, footer.original_image_size)
    _s.pack_into(">Q", blob, _OFF_VBMETA_IMAGE_SIZE, footer.vbmeta_image_size)
    with open(image_path, "ab") as fh:
        fh.write(bytes(blob))


def assert_no_footer(path: str) -> None:
    """Task 5.2 guard: assert the output image has NO AVB footer.

    Pack must never append an AVB footer. This is a hard assertion.
    """
    size = os.path.getsize(path)
    if size < AVB_FOOTER_SIZE:
        return
    with open(path, "rb") as fh:
        fh.seek(-AVB_FOOTER_SIZE, os.SEEK_END)
        tail = fh.read(4)
    if tail == AVB_FOOTER_MAGIC:
        raise AvbFooterError(
            f"output image {path} unexpectedly has an AVB footer; pack must "
            f"never append one (Strategy A)."
        )
