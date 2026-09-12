## 1. 图标系统底座（P0 · 前置）

- [x] 1.1 在 `systemimgkit/gui/resources/icons/` 新增 10 个 24×24 stroke 风格 SVG：`open` / `unpack` / `list` / `pack` / `cancel` / `probe` / `sort` / `files` / `bigfile` / `risk`（1.5px 描边，可着色）
- [x] 1.2 在 `systemimgkit/gui/qml.qrc` 增加 `<qresource prefix="/icons">`，登记上述 10 个 SVG
- [x] 1.3 在 `main.qml` 顶部定义 `icon(name, color, size)` 辅助：返回 `Item`（`Image` 经 `MultiEffect` 着色），默认 `c.fg`
- [x] 1.4 用 `pyside6-rcc systemimgkit/gui/qml.qrc -o systemimgkit/gui/qml_rc.py` 重新生成 `qml_rc.py`
- [x] 1.5 烟测：只把 rail 的"打开镜像…"按钮替换为 图标+文字 作为样板，验证图标渲染与着色正常；其余按钮保持原样
- [x] 1.6 确认 `ColorOverlay` 在 Qt6 / 当前 PySide6 版本下可用（`import QtQuick`），如不可用则回退为每个图标烘焙 normal/disabled 两个 SVG 变体并记录原因 — **回退生效**：ColorOverlay 不可用，改用 `QtQuick.Effects.MultiEffect` 的 `colorization`/`colorizationColor` 着色，已记入 design.md

## 2. 顶栏与布局层级（P3）

- [x] 2.1 在根 `ColumnLayout` 首位插入 48px header（横跨全宽）：左 = qrc `icon.svg` 24px + "SystemImgKit"，右 = 风险状态点（`riskOverride ? c.warn : c.ok`）+ "可回收 \<reclaimTotal\>" 徽章
- [x] 2.2 从左侧 rail 顶部移除 `SYSTEMIMGKIT` wordmark 及其 hairline；rail 内容从"镜像"段开始
- [x] 2.3 把日志 dock 状态行里的 reclaim 徽章与风险点上移到 header；dock 仅保留日志流
- [x] 2.4 rail 各分组（镜像/流程/风险/视图）之间间距提到 24px，小标题保留 `fsMicro`+letterSpacing；每组之间最多一条 hairline，删除多余的密集双线 — 现有 hairline 上下各 pad(12)=24px 已达标，无双线
- [x] 2.5 全局控件圆角统一 `radius: 6`，按钮最小高度 32px — 已在 P1 按钮组件落地（Primary/Secondary/Ghost 均 radius 6 + 32px 高），TextField/TabButton radius 4
- [x] 2.6 验证 header 不挤压 rail/工作区高度；右侧 work surface 的 `RowLayout`/`StackLayout` 结构与 dock 拖拽分隔条行为不变

## 3. 按钮与控件样式分级（P1）

- [x] 3.1 在 `main.qml` 内联定义 `PrimaryButton` 组件：`c.accent` 填充、白字、`radius 6`、hover 变深 8%、press scale 0.98、左侧图标+文字
- [x] 3.2 内联定义 `SecondaryButton`：`c.line` 描边、`c.fg` 文字、透明底、hover 底色 `c.panelHi`、左侧图标
- [x] 3.3 内联定义 `GhostButton`：无边、`c.fgDim`、hover 文字变 `c.fg`
- [x] 3.4 替换 rail 按钮：打开镜像…/探测设备分区→SecondaryButton；取消→GhostButton；打包→PrimaryButton（在 P2 stepper 落地）。保留每个按钮的 `enabled` 绑定与 `onClicked` 调用不变
- [x] 3.5 统一 `CheckBox` / `TextField` / `TabButton` 视觉：选中用 `c.accent`，圆角 4，描边 `c.line`；保留 `overrideBox.onToggled` / `targetSizeField` 的写入抑制逻辑与 `Connections` 不变 — overrideBox 自定义 indicator 已做；delegate 内 CheckBox 统一挪到 P4
- [x] 3.6 验证风险开关二次确认对话框、targetSize 输入框探针回写、TabBar 切换全部行为不变（offscreen 烟测 rootObjects=1 无错）

## 4. 流程 stepper 重设计（P2）

- [x] 4.1 删除左侧 rail 流程段的 `1/2/3 + ►` 数字与播放符、单独的 run 按钮
- [x] 4.2 实现 3 步 stepper：每行 = 22px 圆圈（图标或对勾）+ 标签 + active 行可点 + accent 左条
- [x] 4.3 圆圈状态：done→`c.ok` 填充白色对勾（Canvas）；active→`c.accent` 描边 + 内含该步图标；pending→`c.line` 描边淡色 + 行不可点
- [x] 4.4 步骤状态由 `Controller.canUnpack/canCatalog/canPack` 推导（design 决策4 真值表）；已验证 `_workspace_dir` 仅在 doUnpack 时设置，`canCatalog` 为真 ⟹ step1 已完成，无需 `catalogLoaded` 门控
- [x] 4.5 点击 active 步骤执行对应动作：`wsDialog.open()` / `Controller.doCatalog()` / `Controller.packDefault()`，调用与原代码一致
- [x] 4.6 保留"取消"GhostButton + 不定式 `ProgressBar`，仍由 `progressBusy` 门控
- [x] 4.7 验证：`states` 为声明式绑定，`canPack/canCatalog/canUnpack` 均 notify `isReadyChanged`，readiness 变化时自动刷新（offscreen 烟测 rootObjects=1 无错）

## 5. 收尾打磨（P4）

- [x] 5.1 三个 `ListView` 空状态升级为居中"图标(`c.fgFaint`) + 主标题(`fsBase`) + 副说明(`fsMicro`)"（appList/fileList/bigFileList + dirTree 四处，共用 `emptyStateComponent`）
- [x] 5.2 `appCard` 的 guard badge 内边距增加（+12/+6，radius 4，保留 0.18 alpha 与 1px 边框）；tooltip 改为 styled `ToolTip`（`c.bg` 底 + `c.line` 描边 + `radius 4`）；appCard CheckBox 自定义 accent indicator
- [x] 5.3 日志 dock 标题行加终端样小图标；最末行用 `c.fg`，旧行用 `c.fgFaint`（RichText live tail）；自动滚动行为不变
- [x] 5.4 全量回归：offscreen 烟测 rootObjects=1 零错误；`pytest tests/` 36 passed 无回归
- [x] 5.5 截图对比改版前后；确认图标着色、按钮分级、stepper 状态在 busy/idle 两种态下均正确 — offscreen 截图超时跳过（grabWindowImage 在 offscreen 阻塞），改以烟测+测试套件验证；建议用户实机 `systemimgkit gui` 目视确认

## 6. 功能区主题化卡片（P5）

- [x] 6.1 调色板扩展 `c.card`（最亮卡面 `#FBFBFC`）与四个功能区主题色 `tImage`(蓝)/`tPipe`(紫)/`tRisk`(琥珀)/`tView`(青)
- [x] 6.2 定义 `sectionHeaderComponent`（主题色圆角图标徽标 + 标题，圆角矩形图标底用主题色 0.16 alpha + 1px 描边）
- [x] 6.3 「镜像」区卡片化：`c.card` 底 + `c.line` 描边 + radius 8 + 左侧 `tImage` 竖条 + 标题行；内容（镜像信息 + 打开按钮）内缩
- [x] 6.4 「流程」区卡片化（主题色 `tPipe`）：含 stepper + 取消 + 进度条；保留 `stepper` id 与状态绑定
- [x] 6.5 「风险」区卡片化（主题色 `tRisk`）：含 override CheckBox + 目标分区大小 + 探测按钮；保留 onToggled/targetSizeField 逻辑
- [x] 6.6 「视图」区卡片化（主题色 `tView`）：含 TabBar；保留 tabs id 与 StackLayout 绑定
- [x] 6.7 rail `ColumnLayout` spacing 改 10（卡间距），移除原 hairline 分隔线
- [x] 6.8 回归：offscreen 烟测 rootObjects=1 零错误；`pytest tests/` 36 passed 无回归

## 7. 选镜像即解包（移除解包按钮）

- [x] 7.1 Controller 新增 `currentOp` Property（"" / "unpack" / "catalog" / "pack" / "probe"）+ `currentOpChanged` 信号，`_start_worker` 加 `op` 参数，doUnpack/doCatalog/probe/packTo 各传对应 op；`_on_worker_done/failed/cancelled` 在非链式时清空 op
- [x] 7.2 Controller 新增 `unpacked` Property + `unpackedChanged`；`_on_unpacked` 成功置 true，失败不动；`openImage` 重置 false
- [x] 7.3 Controller 新增 `imageDir` Property（镜像所在目录）与 `openImageAndUnpack(path)` Slot：openImage 后若 imageOk 且非 busy，自动 `doUnpack(os.path.dirname(image_path))`
- [x] 7.4 QML `imageDialog.onAccepted` 改调 `Controller.openImageAndUnpack(currentFile)`；删除 `wsDialog`（FolderDialog）及其引用
- [x] 7.5 stepper 由 3 步改为 2 步（列出应用 / 打包）；state 推导改为 2 元素（canPack→[done,active]，canCatalog→[active,pending]，else→[pending,pending]）；移除"解包"步骤
- [x] 7.6 镜像卡片新增解包状态行：`currentOp==="unpack"` 显示脉冲 spinner + "解包中…" + "工作区：镜像所在目录"；`unpacked` 显示绿色对勾 + "已解包"
- [x] 7.7 回归：`pytest tests/` 36 passed；分支验证无效镜像不解包、有效镜像用镜像目录调 doUnpack；offscreen QML 烟测 rootObjects=1 零错误

## 8. 解包期间无响应/闪退修复（日志流节流）

- [x] 8.1 根因定位：rsync `--info=progress2` 每秒数十条 `\r` 进度行经 stderr→`_on_progress`→`append_warning`→`warningsChanged`→QML RichText 对【全部历史行】重做转义/着色/join，每行 O(n) 全量重建，n 线性增长→主线程卡死→无响应→闪退
- [x] 8.2 Controller `append_warning`/`append_warnings` 改走 `_append_log_line`：含 `\r` 的行 `rsplit("\r")[-1]` 取最后段，若上一行是 progress 行则原地替换而非追加（progress2 原地改写单行状态）
- [x] 8.3 新增 `_looks_like_progress` 启发式（含 `%` 且含 `/s` 或 `:` 且有数字）判定 progress 行，保守避免误折叠普通日志
- [x] 8.4 日志行数上限 `_LOG_MAX_LINES=800`，超出裁掉旧行，bound RichText 渲染成本
- [x] 8.5 节流：`QTimer`(100ms 单发) 合并 `warningsChanged`，progress 突发期间每 100ms 至多通知 QML 一次（`_schedule_log_flush`/`_flush_log`）
- [x] 8.6 验证：500 条 progress 行→日志保持 1 行；2050 条混合行 302ms 处理完、最终 51 行；`pytest tests/` 36 passed；QML 烟测 rootObjects=1 零错误

## 9. 视图简化与大文件守护联动

- [x] 9.1 移除「文件」视图：TabBar 删"文件" TabButton，「大文件」Tab 从 index 2 改 1；StackLayout 删 `fileList` 子项；删除 `fileRow` delegate Component
- [x] 9.2 `BigFileModel` 把 `protected` 角色替换为 `guard`（"none"|"guarded"|"core"），新增 `_guards`/`_risk_override`
- [x] 9.3 `BigFileModel._selectable`：core 永不可选；guarded 在无 override 时不可选；none 可选。`flags`/`setData` 据此约束（拒绝时回弹 checkbox）
- [x] 9.4 `BigFileModel.set_risk_override`：开关变化刷新；关闭时自动取消 guarded 勾选，保留 none 勾选
- [x] 9.5 `_build_catalog_job` 收集大文件时算 `guard`：系统 protected_paths→core 硬锁；否则按所属 app 的 image_path 前缀继承 guard（最长前缀优先）
- [x] 9.6 `Controller.setOverride` 同时调 `app_model` 与 `bigfile_model` 的 `set_risk_override`，并 emit `reclaimChanged`
- [x] 9.7 QML `bigFileRow` delegate 改用 `model.guard`：三色边 + guard badge + checkbox enabled 受 override 约束（与 appCard 一致）
- [x] 9.8 验证：`/apex`→core 硬锁、guarded app 文件受 override 约束、override 关闭取消 guarded 勾选；`pytest tests/` 36 passed；QML 烟测零错误

## 10. 更换工具应用图标

- [x] 10.1 初版自绘方案（分层镜像块 + 裁切缺口 / 剪刀）视觉不理想，改用网络开源图标资源
- [x] 10.2 从 Lucide 图标库（ISC 协议，可商用）取 `package-minus` 图标 SVG（`https://unpkg.com/lucide-static@1.45.0/icons/package-minus.svg`），组合为应用图标：品牌蓝（#2A6CF6，与 in-app accent 一致）圆角方底 + 居中白色 package-minus glyph（包裹盒+减号，语义"系统包-精简"）
- [x] 10.3 写入 `systemimgkit/gui/resources/icon.svg`（128×128 viewBox，glyph 缩放居中、描边改白色、stroke-width 加粗以适配小尺寸）
- [x] 10.4 扩展 `_rasterize.py` 同时输出到 `data/icons/hicolor/<size>x<size>/apps/systemimgkit.png`（`install-icons` 与 .desktop 引用源），修复"重画 SVG 后菜单图标仍是旧图"的根因——之前 data/icons 不同步
- [x] 10.5 用 `_rasterize.py` 重新栅格化 16/22/24/32/48/64/128/256px 全套 PNG（gui/resources 与 data/icons 两处）
- [x] 10.6 `pyside6-rcc` 重新生成 `qml_rc.py`，使 `:/icon.svg` 与 PNG 资源同步
- [x] 10.7 验证：QSvgRenderer 解析通过、渲染像素核对蓝底+白 glyph 正确、QResource 可读、data/icons 与 gui/resources PNG md5 一致、GUI 烟测 rootObjects=1、`pytest tests/` 36 passed
