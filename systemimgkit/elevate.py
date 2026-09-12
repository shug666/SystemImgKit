"""GUI 启动时的一次性 root 提权。

相比"每条命令单独 pkexec"的做法，启动时把整个 GUI 进程以 root 重新启动有两个好处：
  1. 只弹一次授权窗口（而非每次 losetup/mount/... 都弹）。
  2. 整条流水线作为 root 进程直接运行，loop 挂载/rsync/setxattr 不再因
     每条命令的 pkexec 怪异行为而失败。

提权方式：用 pkexec 重新执行本程序，并通过 env 把 DISPLAY / XAUTHORITY 等
显示变量透传给 root 进程，使其窗口仍显示在当前用户的桌面上。强制使用 xcb
（X11）平台，因为 Qt 以 root 身份在 Wayland 下运行不稳定。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

# 透传给 root 进程的显示相关环境变量。
_DISPLAY_ENV_KEYS = (
    "DISPLAY",
    "XAUTHORITY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE",
    "DBUS_SESSION_BUS_ADDRESS",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
)


def _build_pkexec_cmd() -> list[str] | None:
    """构造 pkexec 重启命令；无可用的显示则返回 None。"""
    preserved: dict[str, str] = {}
    for k in _DISPLAY_ENV_KEYS:
        v = os.environ.get(k)
        if v:
            preserved[k] = v
    # 强制 X11：Qt 以 root 在 Wayland 下运行不稳定。
    preserved["QT_QPA_PLATFORM"] = "xcb"
    if not preserved.get("DISPLAY"):
        return None  # 无显示，无法以 root 弹出 GUI
    if not preserved.get("XAUTHORITY"):
        xa = os.path.expanduser("~/.Xauthority")
        if os.path.exists(xa):
            preserved["XAUTHORITY"] = xa
    orig_uid = os.getuid()
    cmd = ["pkexec", "env"]
    for k, v in preserved.items():
        cmd.append(f"{k}={v}")
    # --elevated 标记本次已是提权重启；--orig-uid 记录原用户 uid 以便回写属主。
    cmd += [sys.executable, "-m", "systemimgkit", "gui",
            "--elevated", f"--orig-uid={orig_uid}"]
    return cmd


def try_elevate() -> bool:
    """尝试以 root 重启 GUI。

    返回值的语义：
      - 已是 root：返回 False（无需提权，调用方直接以 root 构建 GUI）。
      - 提权成功：root 子进程接管，本进程随后 sys.exit(0)（不会返回）。
      - 提权被拒/不可用：返回 True（调用方以普通用户身份继续，走 rootless）。

    若提权被拒，会设置环境变量 SIK_NO_ELEVATE=1，使后续 `privilege_wrapper()`
    不再每条命令单独弹 pkexec 窗口（避免反复打扰已拒绝提权的用户）。
    """
    if os.geteuid() == 0:
        return False  # 已是 root
    if not shutil.which("pkexec"):
        os.environ["SIK_NO_ELEVATE"] = "1"
        return True
    cmd = _build_pkexec_cmd()
    if cmd is None:
        os.environ["SIK_NO_ELEVATE"] = "1"
        return True
    try:
        ret = subprocess.run(cmd)
    except OSError:
        os.environ["SIK_NO_ELEVATE"] = "1"
        return True
    if ret.returncode == 0:
        # root 子进程已完成（用户关闭了窗口），本进程退出。
        sys.exit(0)
    # 提权被用户取消或失败 → 以普通用户继续（rootless），并禁止后续重复弹窗。
    os.environ["SIK_NO_ELEVATE"] = "1"
    return True
