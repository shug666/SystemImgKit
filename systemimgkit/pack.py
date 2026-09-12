"""Pack: edited tree -> flashable ext4 image (AVB Strategy A).

Tasks 4.1 (apply deletions to a copy of the tree), 4.2 (size cap), 4.3
(mke2fs -d), 4.4 (restore manifest metadata), 4.5 (e2fsck -fy), 4.6 (optional
sparse), 4.7 (flash.sh for Strategy A), 4.8 (assert no footer + e2fsck clean).

Strategy A: the output is a footerless raw ext4 image. The tool never invokes
avbtool and never appends an AVB footer (asserted by avb.assert_no_footer).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field

from . import avb, catalog
from .errors import SizeCapExceededError, SystemImgKitError, MissingDependencyError, ValidationFailedError
from .runner import CancelToken, CancelledError, privilege_wrapper, run, have_root
from .tools import locate_android_ext4_tools
from .workspace import Workspace

MKE2FS = "mke2fs"
E2FSCK = "e2fsck"
LOSETUP = "losetup"
IMG2SIMG = "img2simg"

# Metadata-restore heartbeat granularity: emit a `⟳ 元数据回写 i/N` progress
# line every N processed entries (see change pack-progress-heartbeat D5).
# Chosen so the common ~6440-entry manifest yields ~6 updates; bounded so a
# large manifest never emits per-entry log spam.
METADATA_HEARTBEAT_EVERY = 1000

# Extra free-space headroom factor when sizing the image. We build at the
# original block count (which already fits the partition), so this only guards
# the staging copy.
HEADROOM_FACTOR = 1.05


@dataclass
class PackResult:
    output_image: str
    sparse_image: str | None
    flash_script: str
    block_count: int
    block_size: int
    e2fsck_clean: bool
    warnings: list[str] = field(default_factory=list)
    metadata_restored: bool = False


def pack(
    workspace: Workspace,
    output_image: str,
    *,
    deletions: list[str] | None = None,
    deletions_file: str | None = None,
    sparse: bool = False,
    vbmeta_image: str | None = None,
    target_blocks: int | None = None,
    on_line=None,
    cancel: CancelToken | None = None,
) -> PackResult:
    """Rebuild a flashable ext4 image from the (edited) extracted tree."""
    output_image = os.path.abspath(output_image)

    # Load manifest (block size/count, metadata entries).
    man = _load_manifest(workspace)
    block_size = man.block_size or 4096
    original_block_count = man.block_count or (man.original_image_size // block_size)
    if original_block_count == 0:
        raise SystemImgKitError("manifest has no block_count/original_image_size; "
                                "cannot size the output image.")

    # Output image size: default to the original partition size; allow a
    # smaller target when the device's system partition is smaller than the
    # original image (common with dynamic super partitions).
    build_block_count = target_blocks or original_block_count
    if target_blocks and target_blocks < original_block_count:
        on_line and on_line(
            f"目标分区: {target_blocks:,} 块 ({target_blocks*block_size/1e9:.2f} GB),"
            f" 原分区 {original_block_count:,} 块 — 按目标大小建镜像")
    elif target_blocks and target_blocks > original_block_count:
        raise SystemImgKitError(
            f"目标分区 {target_blocks:,} 块大于原分区 {original_block_count:,} 块,"
            f"无法增大镜像(工具只用于缩小)。")
    target_bytes = build_block_count * block_size

    # Resolve deletion set.
    if deletions is None and deletions_file is not None:
        deletions = catalog.load_deletions(deletions_file)
    deletions = deletions or []

    warnings: list[str] = []

    # 4.1: hardlink-copy the tree to a staging dir, then apply deletions there.
    # cp -al makes hardlinks (no data duplication); removing staging links does
    # not affect the original tree.
    staging = os.path.join(workspace.root, "staging")
    if os.path.exists(staging):
        shutil.rmtree(staging)
    on_line and on_line("hardlink-copying tree to staging…")
    run(["cp", "-al", workspace.tree, staging], on_line=on_line, cancel=cancel)

    on_line and on_line(f"applying {len(deletions)} deletion(s) to staging…")
    for img_path in deletions:
        rel = img_path.lstrip("/")
        target = os.path.join(staging, rel)
        if os.path.lexists(target):
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target)
            else:
                os.remove(target)

    # 4.2: size check. The staging tree's deduplicated logical size is a rough
    # upper bound on what the rebuilt image must hold.
    staging_size = _du(staging)
    on_line and on_line(
        f"staging tree size={staging_size:,} target image size={target_bytes:,}"
    )
    if man.has_shared_blocks:
        # For shared_blocks images, e2fsdroid applies its own block-level dedup
        # at population time, so the staging _du (inode-deduped logical size)
        # can exceed the partition while the actual rebuilt image still fits.
        # Don't hard-abort here — let e2fsdroid fail if it truly can't fit, and
        # only warn when the staging size is far over (e.g. >110% of partition).
        if staging_size > target_bytes * 1.1:
            on_line and on_line(
                f"WARNING: staging size ({staging_size:,}) is >110% of the "
                f"partition ({target_bytes:,}); the rebuild may not fit even with "
                f"shared_blocks dedup. Consider deleting more apps.")
    elif staging_size > target_bytes:
        raise SizeCapExceededError(
            f"edited tree ({staging_size:,} bytes) exceeds the original image "
            f"size ({target_bytes:,} bytes); cannot fit the partition."
        )

    # 4.3: build the fresh ext4 at the original block count (fits the partition).
    if os.path.exists(output_image):
        os.remove(output_image)

    if man.has_shared_blocks:
        # shared_blocks path: rebuild with the Android e2fsprogs toolchain so
        # duplicate blocks are deduplicated (the source image relied on this to
        # fit; standard mke2fs -d expands them and overflows the partition).
        android = locate_android_ext4_tools()
        missing = [n for n, p in android.items() if not p]
        if missing:
            raise MissingDependencyError(
                "源镜像使用 shared_blocks 去重,需要 Android 的 e2fsdroid 工具链重建,但缺少: "
                + ", ".join(missing) + "。请确保 systemimgkit/ext4tools/linux-x86_64/ 下有这些二进制。"
            )
        amk = android["mke2fs"]
        ae2 = android["e2fsdroid"]
        on_line and on_line(
            f"shared_blocks: building with Android mke2fs + e2fsdroid "
            f"(block_size={block_size}, blocks={build_block_count})…")
        # 1. empty image with the source feature set (shared_blocks is set by
        #    e2fsdroid -s at population time; disable the 1.45.5 defaults the
        #    source image does not have).
        feat = ("^has_journal,^flex_bg,^64bit,^metadata_csum,^resize_inode")
        inode_arg = ["-N", str(man.inode_count)] if man.inode_count else []
        res = run(
            [amk, "-t", "ext4", "-b", str(block_size), "-m", "0", "-L", "/",
             "-O", feat, *inode_arg, output_image, str(build_block_count)],
            on_line=on_line, cancel=cancel, check=False,
        )
        if res.returncode != 0:
            raise SystemImgKitError(
                f"Android mke2fs 建空镜像失败(rc={res.returncode}):\n{res.stdout}"
            )
        # 2. populate with shared_blocks dedup (-s=SHARE_DUP, -e=unix io for a
        #    non-sparse file). Pass -C (fs_config) + -S (file_contexts) so
        #    uid/gid/mode/caps/SELinux are set during population — we can't use
        #    the mount-based _restore_metadata because shared_blocks images
        #    refuse rw mounts.
        fs_config_file = _generate_fs_config(man, workspace)
        file_contexts_file = _generate_file_contexts(man, workspace)
        res = run(
            [ae2, "-e", "-s", "-f", staging, "-a", "/",
             "-C", fs_config_file, "-S", file_contexts_file,
             output_image],
            on_line=on_line, cancel=cancel, check=False,
        )
        if res.returncode != 0:
            raise SystemImgKitError(
                f"e2fsdroid 填充镜像失败(rc={res.returncode}):\n{res.stdout}"
            )
    else:
        # standard path: mke2fs -d. -m 0 frees reserved blocks (Android system
        # partitions don't use them) — matters when the tree is near-full.
        on_line and on_line(f"mke2fs -d (block_size={block_size}, "
                           f"blocks={build_block_count})…")
        res = run(
            [MKE2FS, "-t", "ext4", "-b", str(block_size), "-m", "0",
             "-L", "/", "-d", staging, output_image, str(build_block_count)],
            on_line=on_line, cancel=cancel, check=False,
        )
        if res.returncode != 0:
            raise SystemImgKitError(
                f"mke2fs 无法在 {build_block_count:,} 块内构建镜像(返回码 {res.returncode})。\n"
                f"通常原因:删除的应用不够多,删减后的文件树连同 ext4 元数据仍超过原分区大小。\n"
                f"解决:勾选更多要删除的应用(尤其大型预装应用),或检查 staging 目录大小。\n"
                f"---\n{res.stdout}"
            )

    # 4.4: restore Android filesystem metadata from the manifest.
    metadata_restored = False
    if man.has_shared_blocks:
        # For shared_blocks images, metadata (uid/gid/mode/SELinux/caps) was
        # applied during e2fsdroid population via -C/-S. The mount-based
        # _restore_metadata can't work: shared_blocks images refuse rw mounts.
        metadata_restored = True
        on_line and on_line("metadata applied via e2fsdroid -C/-S (shared_blocks)")
    else:
        pw = privilege_wrapper()
        if pw is not None and not man.incomplete and man.entries:
            on_line and on_line("restoring metadata (uid/gid/xattrs/caps/mtime)…")
            restore_warnings, restored = _restore_metadata(output_image, man, on_line, cancel)
            warnings.extend(restore_warnings)
            metadata_restored = restored
            if not restored:
                on_line and on_line("WARNING: metadata restore was skipped (no root).")
        else:
            if man.incomplete:
                msg = "metadata NOT fully restored: manifest incomplete (rootless unpack)."
            elif not man.entries:
                msg = "metadata restore skipped: manifest has no entries."
            else:
                msg = "metadata NOT fully restored: no root available for the mount step."
            warnings.append(msg)
            on_line and on_line("WARNING: " + msg)

    # 4.5: validate.
    on_line and on_line("e2fsck -fy …")
    res = run([E2FSCK, "-fy", output_image], on_line=on_line, cancel=cancel, check=False)
    # e2fsck returns 0 (clean), 1 (errors corrected), 2 (reboot needed). >1 with
    # uncorrected errors is a hard failure.
    if res.returncode > 1:
        raise ValidationFailedError(
            f"e2fsck reported uncorrected errors (rc={res.returncode}):\n{res.stdout}"
        )
    e2fsck_clean = res.returncode == 0
    if res.returncode == 1:
        warnings.append("e2fsck corrected minor errors automatically.")

    # 4.8: assert no AVB footer on the output (Strategy A guard, Task 5.2).
    avb.assert_no_footer(output_image)

    # 4.6: optional sparse conversion.
    sparse_path: str | None = None
    if sparse:
        if shutil.which(IMG2SIMG):
            sparse_path = output_image + ".sparse"
            on_line and on_line("img2simg → sparse…")
            run([IMG2SIMG, output_image, sparse_path], on_line=on_line, cancel=cancel)
        else:
            warnings.append(f"{IMG2SIMG} not installed; raw ext4 emitted (sparse skipped).")
            on_line and on_line(f"WARNING: {IMG2SIMG} missing, skipping sparse.")

    # 4.7: generate the Strategy-A flash script.
    flash_script = _write_flash_script(
        output_image, sparse_path, vbmeta_image, os.path.dirname(output_image)
    )

    # 提权运行时，产物默认归 root；回写为原用户属主，方便用户直接使用。
    _maybe_chown_to_user(output_image)
    _maybe_chown_to_user(flash_script)
    if sparse_path:
        _maybe_chown_to_user(sparse_path)

    return PackResult(
        output_image=output_image,
        sparse_image=sparse_path,
        flash_script=flash_script,
        block_count=build_block_count,
        block_size=block_size,
        e2fsck_clean=e2fsck_clean,
        warnings=warnings,
        metadata_restored=metadata_restored,
    )


def _load_manifest(workspace: Workspace):
    from . import manifest
    return manifest.Manifest.load(workspace.manifest)


def _du(path: str) -> int:
    """Sum file sizes under `path`, counting each inode once.

    Android system trees use hardlinks (shared blocks) extensively; counting
    st_size per path double-counts the shared data and makes the staging tree
    appear larger than the original image. Dedup by (device, inode) so the
    size reflects real block usage.
    """
    total = 0
    seen: set[tuple[int, int]] = set()
    for dirpath, _, filenames in os.walk(path):
        for fn in filenames:
            try:
                st = os.lstat(os.path.join(dirpath, fn))
            except OSError:
                continue
            key = (st.st_dev, st.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += st.st_size
    return total


def _maybe_chown_to_user(path: str) -> None:
    """提权运行时把产物属主回写为原用户（SIK_ORIG_UID）。

    GUI 以 root 启动后，生成的镜像/脚本默认归 root；回写后用户可直接读写、
    删除这些文件。无 SIK_ORIG_UID 或非 root 时为空操作。
    """
    if os.geteuid() != 0:
        return
    uid_str = os.environ.get("SIK_ORIG_UID")
    if not uid_str:
        return
    try:
        import pwd
        pwent = pwd.getpwuid(int(uid_str))
        os.chown(path, pwent.pw_uid, pwent.pw_gid, follow_symlinks=False)
    except (KeyError, ValueError, OSError):
        pass


def _restore_metadata(image_path, man, on_line, cancel) -> tuple[list[str], bool]:
    """以 root 读写挂载新镜像，回写 manifest 元数据。

    返回 (warnings, restored)。若无法获取 root 挂载（如 pkexec 被拒），跳过
    回写并给出警告，而不是中止整个 pack——调用方据 restored 报告状态。

    对大 manifest，这个循环本身是一段静默的长耗时；每 METADATA_HEARTBEAT_EVERY
    条通过 on_line 发一条 `⟳ 元数据回写 i/N`（i/N 是精确比例，非近似），由
    controller 的原地滚动规则渲染为一行（见 change pack-progress-heartbeat D5）。
    """
    from .mountutil import loop_mount
    from .runner import HEARTBEAT_SENTINEL
    warnings: list[str] = []
    total = len(man.entries)
    processed = 0
    try:
        with loop_mount(image_path, read_only=False, on_line=on_line, cancel=cancel) as mp:
            for entry in man.entries:
                if entry.relpath == "/":
                    continue
                processed += 1
                if on_line and total and processed % METADATA_HEARTBEAT_EVERY == 0:
                    on_line(f"\r{HEARTBEAT_SENTINEL} 元数据回写 {processed}/{total}")
                fpath = os.path.join(mp, entry.relpath.lstrip("/"))
                try:
                    # 属主（对符号链接不跟随）
                    os.chown(fpath, entry.uid, entry.gid, follow_symlinks=False)
                    # 权限（符号链接跳过：Linux 无 lchmod）
                    if entry.type != "symlink":
                        os.chmod(fpath, entry.mode)
                    # 修改时间
                    os.utime(fpath, (entry.mtime, entry.mtime), follow_symlinks=False)
                    # SELinux 上下文
                    if entry.selinux:
                        val = entry.selinux.encode("utf-8") + b"\x00"
                        try:
                            os.setxattr(fpath, "security.selinux", val, follow_symlinks=False)
                        except OSError as e:
                            warnings.append(f"SELinux 回写失败 {entry.relpath}: {e}")
                    # 能力位（原始 xattr 回写）
                    if entry.capabilities:
                        try:
                            os.setxattr(fpath, "security.capability",
                                        bytes.fromhex(entry.capabilities),
                                        follow_symlinks=False)
                        except OSError as e:
                            warnings.append(f"能力位回写失败 {entry.relpath}: {e}")
                except OSError as e:
                    warnings.append(f"元数据回写失败 {entry.relpath}: {e}")
            # final count so the rolling line lands on the exact total
            if on_line and total and processed:
                on_line(f"\r{HEARTBEAT_SENTINEL} 元数据回写 {processed}/{total}")
        return warnings, True
    except SystemImgKitError as e:
        warnings.append(f"元数据回写已跳过：无法挂载镜像（无 root）：{e}")
        return warnings, False


_FLASH_SCRIPT_TEMPLATE = """#!/usr/bin/env bash
# SystemImgKit — Strategy A flash script (AVB verification disabled).
#
# Prerequisites: bootloader UNLOCKED, device connected via USB, adb/fastboot installed.
# This disables verified boot (vbmeta) and flashes the rebuilt system image.
# Review before running. The tool never re-signs images.

set -euo pipefail

SYS_IMG="__SYS__"
SYS_SPARSE="__SPARSE__"
VBMETA_IMG="__VBMETA__"

if [ ! -f "$SYS_IMG" ]; then
  echo "system image not found: $SYS_IMG" >&2; exit 1
fi

# 1. Reboot into fastboot mode
echo "Rebooting to fastboot…"
adb reboot fastboot

# wait for the device to show up in fastboot
echo "Waiting for fastboot device…"
fastboot getvar product 2>/dev/null || sleep 5

# 2. Erase the system partition, then flash the rebuilt image
echo "Erasing system partition…"
fastboot erase system

echo "Flashing system image…"
fastboot flash system "$SYS_IMG"

if [ -n "$SYS_SPARSE" ] && [ -f "$SYS_SPARSE" ]; then
  echo "(sparse variant available at $SYS_SPARSE — use 'fastboot flash system $SYS_SPARSE' if preferred)"
fi

# 3. Flash vbmeta with verification DISABLED so the modified system boots
if [ -n "$VBMETA_IMG" ] && [ -f "$VBMETA_IMG" ]; then
  echo "Flashing vbmeta with verification DISABLED…"
  fastboot --disable-verification flash vbmeta "$VBMETA_IMG"
else
  echo "No vbmeta image provided; disabling verification on the existing vbmeta partition…"
  fastboot --disable-verification flash vbmeta vbmeta.img 2>/dev/null || \\
    echo "WARN: could not flash vbmeta; run 'fastboot --disable-verification flash vbmeta vbmeta.img' manually."
fi

# 4. If flashing reports insufficient space on the dynamic partitions,
#    resize them (then re-run the flash steps above). Uncomment if needed:
#
#   fastboot resize-logical-partition product_a 100
#   fastboot resize-logical-partition product_b 100
#   fastboot resize-logical-partition system_ext_a 100
#   fastboot resize-logical-partition system_ext_b 100

# 5. Wipe userdata and reboot
echo "Wiping userdata and rebooting…"
fastboot -w
fastboot reboot
"""


def _generate_fs_config(man, workspace: Workspace) -> str:
    """Generate a canned fs_config file for e2fsdroid -C.

    Format: path uid gid mode [capabilities=N]
    path is without leading /, or empty string for root.
    """
    path = os.path.join(workspace.root, "fs_config.txt")
    with open(path, "w", encoding="utf-8") as fh:
        for entry in man.entries:
            if entry.relpath == "/":
                p = ""  # root = empty string
            else:
                p = entry.relpath.lstrip("/")
            line = f"{p} {entry.uid} {entry.gid} {entry.mode:o}"
            if entry.capabilities:
                # capabilities as decimal int
                caps = int(entry.capabilities, 16) if isinstance(entry.capabilities, str) else int(entry.capabilities)
                line += f" capabilities={caps}"
            fh.write(line + "\n")
    return path


def _generate_file_contexts(man, workspace: Workspace) -> str:
    """Generate a file_contexts file for e2fsdroid -S (SELinux labels).

    Format (host build, standard selabel backend): two columns —
    regex_path  context  (no mode column).
    Must include the root "/" and lost+found, else selabel_lookup aborts.
    Paths are regex-escaped for exact matching.
    """
    import re as _re
    path = os.path.join(workspace.root, "file_contexts.txt")
    with open(path, "w", encoding="utf-8") as fh:
        # root + lost+found (mke2fs auto-creates; selabel_lookup will query them)
        fh.write("/ u:object_r:rootfs:s0\n")
        fh.write("/lost\\+found u:object_r:rootfs:s0\n")
        for entry in man.entries:
            if not entry.selinux:
                continue
            p = _re.escape(entry.relpath)
            fh.write(f"{p} {entry.selinux}\n")
    return path


def _write_flash_script(sys_img, sparse_img, vbmeta_img, out_dir) -> str:
    script = _FLASH_SCRIPT_TEMPLATE
    script = script.replace("__SYS__", os.path.basename(sys_img))
    script = script.replace("__SPARSE__", os.path.basename(sparse_img) if sparse_img else "")
    # If a vbmeta image is provided, copy it next to the output so flash.sh's
    # relative reference resolves, and set VBMETA_IMG accordingly.
    vbmeta_name = ""
    if vbmeta_img and os.path.isfile(vbmeta_img):
        vbmeta_name = os.path.basename(vbmeta_img)
        dst = os.path.join(out_dir, vbmeta_name)
        if os.path.abspath(vbmeta_img) != os.path.abspath(dst):
            try:
                shutil.copyfile(vbmeta_img, dst)
            except OSError:
                pass
    script = script.replace("__VBMETA__", vbmeta_name)
    path = os.path.join(out_dir, "flash.sh")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(script)
    os.chmod(path, 0o755)
    return path
