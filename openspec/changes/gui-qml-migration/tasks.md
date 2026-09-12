## 1. QML 资源与入口骨架

- [x] 1.1 创建 `systemimgkit/gui/qml/` 目录，放入 `main.qml`（ApplicationWindow + Universal 主题 + ColumnLayout 占位）
- [x] 1.2 改造 `gui/app.py`：`QApplication` + `QQmlApplicationEngine`，从文件系统加载 `main.qml`（dev 路径）；保留 `try_elevate` / `SIK_ORIG_UID` 提权逻辑与 root/降级模式判定
- [x] 1.3 验证空 QML 窗口能启动并显示 root/降级模式标题，CLI 入口不受影响

## 2. Controller 桥接层

- [x] 2.1 新建 `gui/controller.py`：`Controller(QObject)`，暴露 imageInfo / isReady / riskOverride / reclaimTotal / warnings / progressBusy 的 Q_PROPERTY 与 Signal
- [x] 2.2 在 Controller 上实现 `@Slot` 方法骨架：openImage / doUnpack / doCatalog / doPack / cancelWorker / toggleOverride
- [x] 2.3 复用现有 `Worker`（QThread + 信号），在 Controller 中连接 `progress/finished/failed/cancelled` 到 QML 可绑定的属性（仅主线程更新）
- [x] 2.4 将 Controller 与模型注册为 QML context properties，验证 QML 能调用 Slot 并收到 Signal

## 3. AppCardModel（应用目录卡片模型）

- [x] 3.1 新建 `gui/models.py` 中的 `AppCardModel(QAbstractListModel)`：暴露 name/partition/privilege/size/fileCount/guard/checked 等 role
- [x] 3.2 在 `flags()` 中实现禁选规则：核心项不可选，受保护项在未开启 override 时不可选
- [x] 3.3 在 `setData()` 中实现勾选与守护：核心拒绝并回弹，受保护无 override 拒绝并回弹；记录 override 日志
- [x] 3.4 暴露 `selectedApps()` 供打包使用，暴露 `reclaimTotal()` 供可回收大小显示
- [x] 3.5 实现 `sort()`（按名称/大小/guard），供 D4 排序控件调用

## 4. 应用目录卡片视图

- [x] 4.1 `main.qml` 中实现镜像打开面板（名称/大小/格式/AVB页脚），打开后启用解包按钮
- [x] 4.2 实现操作栏（解包/列出应用/打包/取消 + 进度条），绑定 Controller 的 busy/ready 状态
- [x] 4.3 实现风险覆盖开关，绑定 Controller.riskOverride（开启时二次确认）
- [x] 4.4 实现卡片式 `ListView` + 自定义 delegate：勾选框 + 名称 + 分区 + 大小 + 文件数
- [x] 4.5 用颜色/角标表达 guard（核心=锁定红，受保护=琥珀，可删=默认），tooltip 显示守护原因
- [x] 4.6 实现卡片 hover/selected 视觉态（Universal 主题）
- [x] 4.7 实现排序控件（名称/大小/guard），调用 model.sort()

## 5. Files（高级）视图

- [x] 5.1 在 `gui/models.py` 中实现 `FileTreeModel`，遍历工作区 tree，对受保护系统路径应用禁选
- [x] 5.2 `main.qml` 中实现"文件（高级）"tab：紧凑行 delegate 的 ListView（非卡片）
- [x] 5.3 验证受保护系统路径（/apex /system_dlkm 等）标记锁定、不可选

## 6. 警告/状态面板与可回收大小

- [x] 6.1 QML 实现底部状态区：可回收大小标签 + 警告/日志列表（只读）
- [x] 6.2 绑定 Controller.warnings（解包/打包进度行、元数据保真警告、e2fsck 错误、缺依赖错误）
- [x] 6.3 启动时在警告面板注入 root/降级模式提示（沿用 app.py 现有逻辑）

## 7. 打包流程接线

- [x] 7.1 Controller.doPack：收集 selectedApps + selectedFilePaths，调用 `catalog.select_deletions` + `catalog.save_deletions`
- [x] 7.2 通过 Worker 调用 `pack.pack`，完成后展示输出镜像/e2fsck/元数据回写结果与刷机脚本路径
- [x] 7.3 验证风险覆盖日志写入警告面板

## 8. qrc 打包与分发

- [x] 8.1 编写 `systemimgkit/gui/qml.qrc`，登记所有 .qml 文件
- [x] 8.2 在 app.py 增加加载分支：安装环境从 qrc 加载，开发环境从文件系统加载
- [x] 8.3 在 pyproject.toml 配置 package-data 包含 qml/ 与 .qrc

## 9. 移除旧 Widgets 层与对齐

- [x] 9.1 行为对齐校验：对照现有 spec 场景逐项验证（打开/解包/列出/勾选守护/进度/取消/警告/打包）
- [x] 9.2 确认 CLI 与图像管线不受影响（冒烟运行 unpack→pack）
- [x] 9.3 删除 `gui/mainwindow.py` 及残留 Widgets 引用
- [x] 9.4 更新 `gui/__init__.py` 导出，确保 `run_gui` 仍可用

## 10. 普通用户 GUI + root helper 提权

- [x] 10.1 新增 `root_helper.py`：pkexec 调起的 root 入口，unpack/pack 子命令整体复用后端，stdout SIK_RESULT/SIK_ERROR 协议，stderr 进度，SIGTERM 取消 + 入口残挂清理
- [x] 10.2 新增 `gui/rootops.py`：run_unpack/run_pack 用 pkexec+subprocess 调 root_helper，解析 SIK_ 协议，cancel 监视线程即时终止
- [x] 10.3 改 `gui/app.py`：删除整进程提权，GUI 普通用户运行
- [x] 10.4 改 `gui/controller.py`：doUnpack/packTo 改调 rootops，结果从 dict 重建
- [x] 10.5 恢复原生文件对话框（FileDialog/FolderDialog），去 DontUseNativeDialog
- [x] 10.6 file:// URL 路径规范化（_local_path）
- [x] 10.7 Worker 安全关闭（__del__ cancel+wait，app.exec 退出前清理）

## 11. shared_blocks 重建（e2fsdroid）

- [x] 11.1 编译 Android mke2fs + e2fsdroid（静态链接，bundled ext4tools/linux-x86_64/）
- [x] 11.2 manifest 加 features/inode_count/block_count 字段 + has_shared_blocks 属性
- [x] 11.3 unpack 加 _probe_superblock（dumpe2fs -h 探测特性/inode/block_count），传两处 capture_manifest
- [x] 11.4 pack 按 has_shared_blocks 分流：shared 路径用 Android mke2fs + e2fsdroid -e -s
- [x] 11.5 tools.py 加 locate_android_ext4_tools（bundled 优先，PATH 回退）
- [x] 11.6 _du 按 (device,inode) 去重硬链接
- [x] 11.7 shared_blocks 路径放宽 size 检查（e2fsdroid 自身去重）

## 12. SELinux 元数据修复

- [x] 12.1 manifest _getxattr 改 follow_symlinks=False（读 symlink 自身的 xattr）
- [x] 12.2 _add_entry 去掉 symlink 排除（symlink 也读 SELinux）
- [x] 12.3 _generate_fs_config：从 manifest 生成 canned fs_config（path uid gid mode [capabilities=N]）
- [x] 12.4 _generate_file_contexts：两列格式（re.escape(path) + context），含根/lost+found 规则
- [x] 12.5 e2fsdroid 调用加 -C fs_config -S file_contexts
- [x] 12.6 shared_blocks 路径跳过 _restore_metadata（rw mount 不支持）
- [x] 12.7 flash.sh 自动检测 vbmeta.img 并填充 VBMETA_IMG

## 13. 目标分区大小

- [x] 13.1 pack 加 target_blocks 参数（按目标块数建镜像，不允许增大）
- [x] 13.2 root_helper 加 --target-blocks 参数
- [x] 13.3 rootops.run_pack 加 target_blocks 参数
- [x] 13.4 Controller 加 targetBlocks 属性 + probeDevicePartition Slot（fastboot 探测 system_a）
- [x] 13.5 QML 加目标分区大小输入 + 探测设备分区按钮

## 14. 大文件视图

- [x] 14.1 BigFileModel（models.py）：path/size/protected/checked，守护规则在模型层
- [x] 14.2 catalog worker 收集大文件（os.walk + lstat，按大小排序取前 300）
- [x] 14.3 Controller 暴露 bigFileModel，打包时合并 selected_paths
- [x] 14.4 QML 加"大文件"标签页 + bigFileRow delegate
- [x] 14.5 应用勾选同步到大文件（setSelectedAppPaths + _covered_by_app）
- [x] 14.6 可回收大小含大文件（bigfile_model.selected_size + dataChanged 触发 reclaimChanged）

## 15. 解包后自动列出应用

- [x] 15.1 _on_unpacked 末尾自动调 doCatalog
- [x] 15.2 doCatalog 改走 Worker 后台线程（build_catalog + 收集文件列表不阻塞 UI）
- [x] 15.3 _on_cataloged 发 isReadyChanged 让 canPack 重新求值
