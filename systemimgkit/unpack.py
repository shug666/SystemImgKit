"""Unpack: system.img -> file tree + metadata manifest.

Tasks 2.3 (root-gated RO mount + rsync), 2.5 (rootless debugfs rdump fallback),
2.6 (source image never modified).

Pipeline:
  1. ensure_supported()        (format + AVB footer detection)
  2. strip_footer()            -> footerless working copy (source untouched)
  3. mount RO (root) OR debugfs rdump (rootless)
  4. capture_manifest()        (root-gated: full; rootless: incomplete)
  5. rsync tree out (root-gated) -- already extracted by rdump in rootless
  6. save manifest; record source mtime/size for the invariance test
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass

from . import avb, imagefmt, manifest
from .errors import SystemImgKitError
from .runner import CancelToken, CancelledError, privilege_wrapper, run
from .workspace import Workspace, precheck

# Tools that must be present for the rootless fallback.
DEBUGFS = "debugfs"
RSYNC = "rsync"


@dataclass
class UnpackResult:
    workspace: Workspace
    footer_stripped: bool
    original_image_size: int
    incomplete: bool
    source_size: int
    source_mtime: float
    app_count: int = 0


def _probe_superblock(image_path: str) -> "tuple[list[str], int, int]":
    """Probe the ext4 superblock of `image_path` via dumpe2fs -h.

    Returns (features, inode_count, block_count). Used to detect shared_blocks
    and capture the exact filesystem geometry for rebuild. Reads the file
    directly (no root needed); the AVB footer at EOF does not affect the
    superblock. Best-effort: returns ([], 0, 0) on failure.
    """
    import shutil
    import subprocess
    import re
    dumpe2fs = shutil.which("dumpe2fs")
    if not dumpe2fs:
        return [], 0, 0
    try:
        out = subprocess.run(
            [dumpe2fs, "-h", image_path],
            capture_output=True, text=True, check=False,
        ).stdout
    except OSError:
        return [], 0, 0
    features: list[str] = []
    inodes = 0
    blocks = 0
    for line in out.splitlines():
        m = re.match(r"Filesystem features:\s*(.*)", line)
        if m:
            features = [f.strip() for f in m.group(1).split() if f.strip()]
        m = re.match(r"Inode count:\s*(\d+)", line)
        if m:
            inodes = int(m.group(1))
        m = re.match(r"Block count:\s*(\d+)", line)
        if m:
            blocks = int(m.group(1))
    return features, inodes, blocks


def unpack(
    image_path: str,
    workspace_dir: str,
    *,
    on_line=None,
    cancel: CancelToken | None = None,
    allow_rootless: bool = True,
) -> UnpackResult:
    """Unpack `image_path` into `workspace_dir`. See module docstring."""
    image_path = os.path.abspath(image_path)
    if not os.path.isfile(image_path):
        raise SystemImgKitError(f"image not found: {image_path}")

    source_size = os.path.getsize(image_path)
    source_mtime = os.path.getmtime(image_path)

    # Free-space precheck.
    precheck(workspace_dir, source_size)

    fmt, footer_presence = imagefmt.ensure_supported(image_path)
    on_line and on_line(f"format={fmt.value} avb_footer={footer_presence.value}")

    ws = Workspace(root=workspace_dir)
    os.makedirs(ws.root, exist_ok=True)
    os.makedirs(ws.tree, exist_ok=True)

    # 读取 AVB 页脚（仅解析，不复制）。original_image_size = 干净 ext4 的字节数。
    footer = avb.read_footer(image_path)
    stripped = footer is not None
    original_size = footer.original_image_size if footer else source_size
    on_line and on_line(
        f"avb_footer={'present' if stripped else 'absent'} "
        f"original_image_size={original_size}"
    )

    # 探测 ext4 超级块（特性 + inode 数），用于 shared_blocks 重建检测。
    features, inode_count, real_block_count = _probe_superblock(image_path)
    if "shared_blocks" in features:
        on_line and on_line("detected shared_blocks: rebuild will use e2fsdroid")

    # 2. 提取 + 捕获 manifest。优先 root 只读挂载；失败降级 rootless。
    pw = privilege_wrapper()
    incomplete = None
    if pw is not None:
        try:
            incomplete = _extract_root_gated(
                ws, image_path, original_size, stripped, on_line, cancel,
                features, inode_count, real_block_count
            )
        except (SystemImgKitError, CancelledError) as e:
            if isinstance(e, CancelledError):
                raise
            on_line and on_line(
                f"root 只读挂载失败（{type(e).__name__}）；降级为 rootless debugfs。"
            )
            incomplete = None
    if incomplete is None:
        if not allow_rootless:
            raise SystemImgKitError(
                "需要 root 权限进行只读挂载，且 rootless 降级已被禁用。"
            )
        on_line and on_line(
            "警告：使用 rootless debugfs 降级（SELinux 上下文/能力位可能不完整）。"
        )
        incomplete = _extract_rootless(ws, image_path, original_size, stripped,
                                       footer, on_line, cancel,
                                       features, inode_count, real_block_count)

    # 3. Sanity: the source image must be byte-for-byte unchanged.
    _verify_source_unchanged(image_path, source_size, source_mtime)

    return UnpackResult(
        workspace=ws,
        footer_stripped=stripped,
        original_image_size=original_size,
        incomplete=incomplete,
        source_size=source_size,
        source_mtime=source_mtime,
    )


def _extract_root_gated(ws, image_path, original_size, stripped, on_line, cancel,
                        features=None, inode_count=0, block_count=0) -> bool:
    """以 root 只读挂载源镜像（用 sizelimit 跳过 AVB 页脚），rsync 提取并捕获完整 manifest。

    不复制镜像：losetup --sizelimit original_image_size 把设备限定在干净 ext4 部分，
    源文件全程只读。仅在无 AVB 页脚时 size_limit=None（挂载整个文件）。
    """
    from .mountutil import loop_mount
    size_limit = original_size if stripped else None
    with loop_mount(image_path, read_only=True, size_limit=size_limit,
                    on_line=on_line, cancel=cancel) as mp:
        on_line and on_line("捕获元数据清单…")
        man = manifest.capture_manifest(
            mp,
            original_image_size=original_size,
            footer_stripped=stripped,
            incomplete=False,
            features=features,
            inode_count=inode_count,
            block_count=block_count or 0,
        )
        man.save(ws.manifest)
        on_line and on_line(f"清单：{len(man.entries)} 个条目")

        on_line and on_line("rsync 提取文件树（保留 xattr/硬链接）…")
        run(
            [RSYNC, "-aHAX", "--numeric-ids", "--info=progress2",
             mp + "/", ws.tree + "/"],
            on_line=on_line, cancel=cancel,
        )
    return False  # 完整（非降级）


def _extract_rootless(ws, image_path, original_size, stripped, footer,
                      on_line, cancel, features=None, inode_count=0,
                      block_count=0) -> bool:
    """Rootless 降级：debugfs rdump 提取文件树；manifest 标记为不完整。

    debugfs 会读取整个文件，因此若镜像带 AVB 页脚，必须先剥页脚生成工作副本
    （这是 rootless 路径不可避免的复制；root 路径用 sizelimit 挂载避免此复制）。

    `debugfs rdump` 会把属主恢复成原始 uid/gid，非 root 用户对 root 属主文件
    会刷大量 "Operation not permitted while changing ownership" 警告。这是预期
    的（文件内容正常提取，仅属主/xattr 丢失——正是 incomplete 标记所记录的）。
    我们过滤掉这些良性行，只上报真正的提取错误。
    """
    # rootless 路径需要一份剥页脚的副本供 debugfs 读取（root 路径不需要）。
    work = ws.work_image
    if stripped and footer is not None:
        on_line and on_line("剥 AVB 页脚生成工作副本（rootless 需要）…")
        avb.strip_footer(image_path, work, footer=footer)
    elif image_path != work:
        # 无页脚也复制一份，保持 debugfs 输入与源解耦。
        import shutil
        shutil.copyfile(image_path, work)

    on_line and on_line("debugfs rdump /（rootless）…")

    def _filter(line: str) -> None:
        low = line.lower()
        benign = ("operation not permitted while changing ownership" in low
                  or "rdump: operation not permitted" in low)
        if benign:
            return  # 过滤预期的属主失败
        if on_line:
            on_line(line)

    run(
        [DEBUGFS, "-R", f"rdump / {ws.tree}", work],
        on_line=_filter, cancel=cancel,
    )
    on_line and on_line("debugfs rdump 完成（属主/xattr 未保留——rootless 预期行为）。")
    on_line and on_line("从提取的树捕获部分 manifest…")
    notes = [
        "Captured via rootless debugfs rdump fallback.",
        "uid/gid/SELinux/capabilities may be inaccurate and are not restored.",
        "debugfs ownership-change warnings were filtered as benign.",
    ]
    man = manifest.capture_manifest(
        ws.tree,
        original_image_size=original_size,
        footer_stripped=stripped,
        incomplete=True,
        capture_notes=notes,
        features=features,
        inode_count=inode_count,
        block_count=block_count or 0,
    )
    man.save(ws.manifest)
    on_line and on_line(f"manifest（不完整）：{len(man.entries)} 个条目")
    return True


def _verify_source_unchanged(image_path: str, size: int, mtime: float) -> None:
    """Task 2.6: assert the source image was not modified in place."""
    now_size = os.path.getsize(image_path)
    now_mtime = os.path.getmtime(image_path)
    if now_size != size or now_mtime != mtime:
        raise SystemImgKitError(
            f"INVARIANT VIOLATION: source image changed during unpack "
            f"(size {size}->{now_size}, mtime {mtime}->{now_mtime})."
        )
