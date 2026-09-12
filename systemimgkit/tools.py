"""External-tool dependency probing.

Tasks 1.3: probe for the e2fsprogs / android-tools binaries the pipeline relies
on and report what is missing.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

from .errors import MissingDependencyError

# Tools grouped by criticality.
# required: the pipeline cannot run without these.
# optional: enable a feature (sparse output, metadata restore caps).
REQUIRED_TOOLS = [
    "debugfs",   # rootless fallback extraction + metadata inspection
    "mke2fs",    # rebuild ext4 from tree
    "e2fsck",    # validate rebuilt image
    "dumpe2fs",  # read superblock / block count
    "tune2fs",   # adjust fs flags if needed
    "rsync",     # root-gated RO-mount extraction (preserves xattrs/hardlinks)
]

OPTIONAL_TOOLS = {
    "img2simg": "sparse image output (raw ext4 is used otherwise)",
    "sudo": "read-only loop mount for high-fidelity metadata capture",
    "pkexec": "polkit-gated root for the mount step (alternative to sudo)",
    "losetup": "set up the loop device for mounting",
    "mount": "mount the image read-only",
}
# Note: SELinux contexts and capabilities are restored via os.setxattr (no
# external setfattr/setcap binary required).


@dataclass
class ToolReport:
    missing_required: list[str] = field(default_factory=list)
    missing_optional: dict[str, str] = field(default_factory=dict)
    available: dict[str, str] = field(default_factory=dict)  # name -> resolved path

    @property
    def ok(self) -> bool:
        return not self.missing_required

    def summary(self) -> str:
        lines: list[str] = []
        if self.ok:
            lines.append("All required tools are available.")
        else:
            lines.append("Missing REQUIRED tools: " + ", ".join(self.missing_required))
        if self.missing_optional:
            opt = "; ".join(f"{k} ({v})" for k, v in self.missing_optional.items())
            lines.append("Missing optional tools: " + opt)
        return "\n".join(lines)


def check_tools() -> ToolReport:
    """Probe the PATH for every required and optional tool."""
    report = ToolReport()
    for name in REQUIRED_TOOLS:
        path = shutil.which(name)
        if path is None:
            report.missing_required.append(name)
        else:
            report.available[name] = path
    for name, desc in OPTIONAL_TOOLS.items():
        path = shutil.which(name)
        if path is None:
            report.missing_optional[name] = desc
        else:
            report.available[name] = path
    return report


def require_tools() -> ToolReport:
    """Like check_tools() but raise if any required tool is missing."""
    report = check_tools()
    if not report.ok:
        raise MissingDependencyError(report.summary())
    return report


# ---- Android e2fsprogs toolchain (supports shared_blocks) ----------------
# Bundled at systemimgkit/ext4tools/linux-x86_64/; falls back to PATH. These
# are needed only when the source image uses the shared_blocks feature.

_ANDROID_EXT4_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),  # systemimgkit/
    "ext4tools", "linux-x86_64",
)


def _locate(name: str) -> str | None:
    bundled = os.path.join(_ANDROID_EXT4_DIR, name)
    if os.path.isfile(bundled) and os.access(bundled, os.X_OK):
        return bundled
    return shutil.which(name)


def locate_android_ext4_tools() -> dict[str, str]:
    """Resolve the Android mke2fs / e2fsdroid / e2fsck binaries.

    Returns a dict with keys 'mke2fs', 'e2fsdroid', 'e2fsck' → absolute paths.
    Missing tools map to "" so callers can check availability.
    """
    out: dict[str, str] = {}
    for name in ("mke2fs", "e2fsdroid", "e2fsck"):
        out[name] = _locate(name) or ""
    return out
