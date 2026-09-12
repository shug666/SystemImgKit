"""共享的 loop 挂载助手（unpack 与 pack 共用）。

用正则只提取形如 /dev/loopN 的行，避免 pkexec 的 GLib 警告污染输出导致
解析到错误的"loop 设备名"（这是无 root 降级误判的根因）。
"""

from __future__ import annotations

import os
import re
import tempfile
from contextlib import contextmanager

from .errors import SystemImgKitError
from .runner import privilege_wrapper, run

_LOOP_RE = re.compile(r"^/dev/loop\d+\s*$")


def parse_loop_device(output: str) -> str:
    """从 losetup --show 的输出里提取 loop 设备路径。

    pkexec 可能在 stdout/stderr 里混入 GLib 警告；只接受 /dev/loopN 行。
    """
    for line in output.splitlines():
        if _LOOP_RE.match(line):
            return line.strip()
    raise SystemImgKitError(
        f"无法从 losetup 输出中解析 loop 设备路径：\n{output}"
    )


@contextmanager
def loop_mount(image_path: str, *, read_only: bool = True, on_line=None,
               cancel=None, size_limit: int | None = None):
    """建立 loop 设备并挂载镜像，yield 挂载点；退出时自动 umount + detach。

    需要 root（或通过 privilege_wrapper() 的 pkexec/sudo 前缀）。在提权后的
    GUI 进程里 privilege_wrapper() 返回 []，命令直接以 root 运行。

    size_limit：若给定，用 `losetup --sizelimit <size_limit>` 把设备限定在
    文件前 size_limit 字节。用于挂载带 AVB 页脚的 system.img 时跳过页脚，
    无需先复制一份剥页脚的副本（省一次与镜像等大的复制）。
    """
    pw = privilege_wrapper()
    mountpoint = tempfile.mkdtemp(prefix="sik_mount_")
    loop: str | None = None
    mounted = False
    try:
        losetup_flags = ["-f", "-r", "--show"] if read_only else ["-f", "--show"]
        if size_limit is not None:
            losetup_flags += ["-o", "0", "--sizelimit", str(size_limit)]
        on_line and on_line("建立 loop 设备…")
        res = run([*pw, "losetup", *losetup_flags, image_path],
                  on_line=on_line, cancel=cancel)
        loop = parse_loop_device(res.stdout)
        on_line and on_line(f"loop 设备：{loop}")
        on_line and on_line(f"{'只读' if read_only else '读写'}挂载…")
        run([*pw, "mount", "-o", "ro" if read_only else "rw", loop, mountpoint],
            on_line=on_line, cancel=cancel)
        mounted = True
        yield mountpoint
    finally:
        if mounted:
            try:
                run([*pw, "umount", mountpoint], check=False)
            except SystemImgKitError:
                pass
        if loop:
            try:
                run([*pw, "losetup", "-d", loop], check=False)
            except SystemImgKitError:
                pass
        try:
            os.rmdir(mountpoint)
        except OSError:
            pass
