# SystemImgKit

解包、精简、重打包 Android **system-as-root** 架构的 ext4 系统镜像（适用于联想 ZUI / GMS 固件）。

把 `system.img` 解包成可浏览的应用目录树，按安全等级（核心 / 受保护 / 可删除）标记可删应用，再重建出一个可刷写的镜像。配套生成 `flash.sh` 刷机脚本，关闭 AVB 校验后直接 fastboot 刷入。

## 功能特点

- **图形界面 (GUI)**：PySide6 + QML 桌面应用，可视化浏览应用列表、勾选删除项
- **安全分级删除**：内置守护清单（`guardlist.yaml`），核心应用永不删除，受保护应用需手动开启风险覆盖
- **真实进度反馈**：打包时 `mke2fs -d` / `e2fsdroid` 填充阶段的静默期有实时心跳（真实已写字节数），不再"卡在开头"
- **shared_blocks 支持**：自动识别并使用 Android e2fsdroid 工具链重建去重镜像
- **元数据完整回写**：uid/gid/权限/SELinux 上下文/能力位/时间戳
- **AVB Strategy A**：输出无页脚的原始 ext4 镜像，刷机脚本关闭 verified boot，工具本身从不重新签名
- **取消可中断**：打包/解包过程中可随时取消（需再次授权 root 杀进程）

## 环境要求

- **Linux**（已内置 `linux-x86_64` 的 Android `mke2fs` / `e2fsdroid`）
- **Python ≥ 3.12**
- **PySide6 ≥ 6.6**（GUI 所需）
- 系统外部工具：`e2fsprogs`（`mke2fs`、`e2fsck`、`resize2fs`、`debugfs`）、`rsync`
- 可选：`img2simg`（生成稀疏镜像，未安装则输出原始 ext4）、`adb`/`fastboot`（刷机）
- 刷机需要：**已解锁 bootloader** 的设备

用以下命令检测依赖工具是否齐全：

```bash
systemimgkit check-tools
```

## 安装

```bash
git clone git@github.com:shug666/SystemImgKit.git
cd SystemImgKit
pip install .
```

这会安装 `systemimgkit` 命令、GUI（QML）、守护清单和应用图标资源。

> 建议在虚拟环境中安装：
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install .
> ```

## 使用方式

### 图形界面 (GUI)

```bash
systemimgkit gui
```

GUI 以普通用户身份运行（文件选择对话框可访问任意目录），解包/打包操作在需要 root 时通过 `pkexec` 弹窗授权。

**GUI 操作流程：**
1. 打开 `system.img` → 自动解包到镜像所在目录
2. 自动列出应用目录 → 按安全等级勾选要删除的应用
3. （可选）探测设备分区大小，设定目标分区容量
4. 点击"打包" → 生成 `system_new.img` + `flash.sh`
5. 取消授权窗口弹出 → 输入密码 → 镜像写入完成

打包过程中底部日志显示实时进度；进度条中间嵌入"取消"按钮，点击取消会再次弹出 root 授权以终止后台进程。

### 命令行 (CLI)

```bash
# 检测外部依赖工具
systemimgkit check-tools

# 解包：把 system.img 解到工作区
systemimgkit unpack <image.img> -w <工作区目录>

# 列出应用（表格形式）；--json 输出 JSON
systemimgkit catalog -w <工作区目录> --list

# 重打包：根据删除清单重建镜像
systemimgkit pack -w <工作区目录> -o <输出镜像> \
    --deletions <删除清单文件> \
    --vbmeta <vbmeta.img>     # 生成 flash.sh 时引用，关闭 AVB 校验
    [--sparse]                # 同时输出稀疏镜像
```

**删除清单文件**：每行一个镜像内相对路径（如 `/system/app/Foo`），打包时会从副本中删除这些条目。

### 刷机

打包生成的 `flash.sh` 会自动放在输出镜像旁。**刷机前务必审阅脚本**，确认设备已解锁 bootloader、已连接 USB：

```bash
cd <输出目录>
./flash.sh
```

脚本会：重启进 fastboot → 擦除 system 分区 → 刷入新镜像 → 用 `--disable-verification` 刷 vbmeta（关闭验证启动）→ 清 userdata → 重启。

> ⚠️ 该工具从不重新签名镜像。关闭 AVB 验证后才能启动修改过的 system，请确保你理解这意味着系统完整性校验被禁用。

## 应用图标与菜单集成

GUI 启动时会自动设置窗口图标。若要让 SystemImgKit 出现在应用菜单/启动器中，安装 `.desktop` 条目和 hicolor 图标到用户目录（无需 root）：

```bash
systemimgkit install-icons
```

这会把 `systemimgkit.desktop` 和 hicolor PNG（16–256px，外加可缩放 SVG）复制到 `~/.local/share`。系统级安装则用 `--prefix /usr/share`（需写权限）。

前提：`systemimgkit` 需在 `PATH` 上（`.desktop` 的 `Exec=` 是 `systemimgkit gui`）。若装在虚拟环境里，激活它或把命令软链到 `PATH`。

## 项目结构

```
systemimgkit/
├── cli.py              # 命令行入口
├── pack.py             # 打包：重建 ext4 镜像（AVB Strategy A）
├── unpack.py           # 解包：剥离 AVB 页脚 + 提取文件树
├── catalog.py          # 应用目录化与安全分级
├── manifest.py         # 镜像元数据捕获与回写
├── avb.py              # AVB 页脚检测/剥离
├── imagefmt.py         # 镜像格式校验
├── root_helper.py      # root 子进程（pkexec 调用）：解包/打包的 root 操作
├── runner.py           # 子进程运行 + 取消 + 进度回调
├── data/
│   └── guardlist.yaml  # 安全分级守护清单（generic + zui 叠加）
├── ext4tools/          # 内置 Android e2fsprogs 二进制（mke2fs/e2fsdroid）
└── gui/                # PySide6 + QML 图形界面
    ├── app.py          # GUI 入口
    ├── controller.py   # QML ↔ Python 桥接
    ├── models.py       # 应用/文件树模型
    ├── rootops.py      # GUI 侧 root 助手调用
    ├── workers.py      # QThread 后台任务
    └── qml/main.qml     # 界面
```

## 许可证

MIT
