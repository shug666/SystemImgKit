"""SystemImgKit — unpack, debloat, and repack Android system-as-root ext4 images.

A desktop (PySide6) + CLI tool for removing bundled/bloat APKs from a stock
system.img (ZUI/GMS) and rebuilding a flashable image without corrupting
block-dedup (shared_blocks) or requiring AVB re-signing.
"""

__version__ = "0.1.0"
