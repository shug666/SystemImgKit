#!/usr/bin/env bash
# install-deps.sh — 安装 SystemImgKit 便携包在 Ubuntu 20.04 上运行所需的宿主级依赖。
#
# 这个脚本安装的是冻结包无法（也不应）内置的系统包：e2fsprogs 工具链、rsync、
# Android sparse/adb/fastboot 工具、pkexec 提权所需的 policykit-1，以及 Qt6 GUI
# 运行期图形库。脚本幂等，可重复运行。
#
# 用法：  ./install-deps.sh

set -euo pipefail

if [[ $EUID -eq 0 ]]; then
    echo "请不要以 root 运行；脚本会在需要时通过 sudo 提权。" >&2
    exit 1
fi

echo "==> 安装 SystemImgKit 运行期宿主依赖（Ubuntu 20.04）"

# --- 安装软件包列表 -------------------------------------------------------
# e2fsprogs               mke2fs / e2fsck / resize2fs / debugfs / dumpe2fs / tune2fs（必需）
# rsync                   高保真解包提取（必需）
# android-sdk-libsparse-utils  提供 img2simg / simg2img（可选：稀疏镜像）
# android-sdk-ext4-utils       Android ext4 工具配套
# adb fastboot            刷机（可选）
# policykit-1             pkexec 提权（GUI root 操作链必需）
# libgl1 libegl1 libxkbcommon0 libdbus-1-3  Qt6 GUI 运行期图形库
PACKAGES=(
    e2fsprogs
    rsync
    android-sdk-libsparse-utils
    android-sdk-ext4-utils
    adb
    fastboot
    policykit-1
    libgl1
    libegl1
    libxkbcommon0
    libdbus-1-3
)

# android-sdk-* 工具包在 universe 源；启用 universe（20.04 通常默认开启）。
echo "==> 启用 universe 源"
sudo add-apt-repository -y universe 2>/dev/null || true

echo "==> apt update"
sudo apt-get update -qq

echo "==> 安装：${PACKAGES[*]}"
sudo apt-get install -y --no-install-recommends "${PACKAGES[@]}"

echo "==> 检查关键工具"
for tool in mke2fs e2fsck debugfs rsync pkexec; do
    if command -v "$tool" >/dev/null 2>&1; then
        echo "    ✓ $tool"
    else
        echo "    ✗ $tool 缺失（请检查安装是否成功）" >&2
    fi
done

cat <<'NOTE'

依赖安装完成。接下来：
  1. 解压便携包：  tar xzf SystemImgKit-*-ubuntu-20.04-x86_64.tar.gz
  2. 进入目录：    cd systemimgkit/
  3. 启动 GUI：    ./systemimgkit
  4. 首次解包/打包会弹出 pkexec 授权窗口，输入你的密码即可。

NOTE
