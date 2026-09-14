"""QML ↔ Python bridge for the SystemImgKit GUI.

A single `Controller(QObject)` exposes the operational surface (open image,
unpack/catalog/pack, cancel, risk-override) to QML via Slots and binds
view state via Properties/Signals. It owns the `Worker` lifecycle and the
two item models. The backend (`unpack`/`catalog`/`pack`) and `Worker` are
reused unchanged — this object only re-wires them to QML.

The Controller is dialog-free: file/message/confirm dialogs live in QML
(QtQuick.Dialogs). The Controller communicates modal needs through signals
(`infoMessage`, `errorMessage`, `guardBlocked`) that QML surfaces, and
receives the user's answers back through Slots. Guard authorization stays
in the models (design D3): the Controller forwards override state to
`AppCardModel` and lets it reject illegal selections.
"""

from __future__ import annotations

import os

from PySide6.QtCore import (
    QObject, Signal, Slot, Property, QTimer,
)

from .. import catalog, imagefmt, manifest
from ..runner import HEARTBEAT_SENTINEL, cancel_debug
from ..workspace import Workspace
from . import rootops
from .models import AppCardModel, FileTreeModel, BigFileModel
from .workers import Worker


def _build_catalog_job(tree: str, on_line) -> "tuple | None":
    """Worker-thread job: build the catalog and collect the file-tree listing.

    Returns (catalog, tree, file_rows, big_file_rows) where:
      - file_rows: [(relpath, protected)] for FileTreeModel (directories)
      - big_file_rows: [(relpath, size, guard)] for BigFileModel, the largest
        files (by size) across the whole tree, capped at ~300 entries. `guard`
        is "none"|"guarded"|"core": a big file inherits the guard level of the
        app it belongs to (by image_path prefix), so the "允许删除受保护应用"
        toggle constrains big-file deletion the same way it constrains app
        deletion. Files not under any app dir are "none".
    """
    import os
    on_line and on_line("遍历应用目录…")
    try:
        cat = catalog.build_catalog(tree)
    except Exception:  # noqa: BLE001
        return None
    on_line and on_line("收集文件列表…")
    protected_paths = cat.protected_paths
    # Map image_path prefix → guard level, longest-prefix-first so a file
    # matches its closest enclosing app dir.
    app_prefixes = sorted(
        ((a.image_path, a.guard) for a in cat.apps),
        key=lambda x: len(x[0]), reverse=True,
    )

    def guard_of(rel: str) -> str:
        # System-protected paths (/apex, /system_dlkm, …) are hard-locked at
        # ANY time — treat as core. Otherwise inherit the guard level of the
        # app the file belongs to (by image_path prefix).
        if catalog.is_protected(rel, protected_paths):
            return "core"
        for prefix, g in app_prefixes:
            if rel == prefix or rel.startswith(prefix + "/"):
                return "core" if g is catalog.GuardLevel.CORE else (
                    "guarded" if g is catalog.GuardLevel.GUARDED else "none")
        return "none"

    dir_rows: list[tuple[str, bool]] = []
    big_files: list[tuple[str, int, str]] = []
    for dirpath, _d, filenames in os.walk(tree):
        rel_dir = "/" + os.path.relpath(dirpath, tree)
        rel_dir = "/" if rel_dir == "/." else rel_dir
        dir_rows.append((rel_dir, catalog.is_protected(rel_dir, protected_paths)))
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not stat_is_file(st):
                continue
            rel = "/" + os.path.relpath(full, tree)
            big_files.append((rel, st.st_size, guard_of(rel)))
    # keep the largest files (sort by size desc), cap at 300
    big_files.sort(key=lambda r: -r[1])
    big_file_rows = big_files[:300]
    return cat, tree, dir_rows, big_file_rows


def stat_is_file(st) -> bool:
    import stat as _stat
    return _stat.S_ISREG(st.st_mode) and not _stat.S_ISLNK(st.st_mode)


def _probe_job(block_size: int, on_line, cancel) -> "dict | None":
    """Worker-thread job: probe the connected device's system_a partition.

    Preflights with `fastboot devices` (short timeout) so a missing device is
    reported instantly instead of hanging the (formerly main-thread) call.
    Returns ``{"ok": True, "size_bytes": …, "blocks": …}`` on success or
    ``{"ok": False, "error": …}`` on failure. Never raises — the Worker
    routes failures through the returned dict via ``_on_probed``.
    """
    import re
    import subprocess

    def _run(cmd, timeout):
        return subprocess.run(cmd, capture_output=True, text=True,
                              check=False, timeout=timeout)

    try:
        # Preflight: is any device present in fastboot mode? `fastboot
        # devices` prints a "<serial>	fastboot" line per attached device.
        d = _run(["fastboot", "devices"], timeout=5)
        devices = (d.stdout or "").strip()
    except FileNotFoundError:
        return {"ok": False, "error": "未找到 fastboot 程序，请确认已安装 Android platform-tools。"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "fastboot 无响应（设备未连接或驱动异常）。"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"探测失败: {e}"}

    if not devices:
        return {"ok": False,
                "error": "未检测到处于 fastboot 模式的设备。请将设备进入 fastboot 并用 USB 连接。"}

    on_line and on_line("已检测到设备，读取 system_a 分区大小…")
    try:
        r = _run(["fastboot", "getvar", "partition-size:system_a"], timeout=30)
        # fastboot prints getvar results to stderr, not stdout.
        out = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "读取分区大小超时（设备未响应 getvar）。"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"读取分区大小失败: {e}"}

    m = re.search(r"partition-size:system_a:\s*(0x[0-9a-fA-F]+)", out)
    if not m:
        return {"ok": False,
                "error": "未找到设备 system_a 分区（该设备可能没有 system_a 分区）。"}
    size_bytes = int(m.group(1), 16)
    bs = block_size or 4096
    blocks = size_bytes // bs
    return {"ok": True, "size_bytes": size_bytes, "blocks": blocks}


class Controller(QObject):
    # ---- property-change signals ----
    imageInfoChanged = Signal()
    isReadyChanged = Signal()
    riskOverrideChanged = Signal()
    reclaimChanged = Signal()
    warningsChanged = Signal()
    progressBusyChanged = Signal()
    catalogLoadedChanged = Signal()
    sectionsChanged = Signal()
    # Fires whenever the target partition size (in blocks) changes, from a
    # probe, manual QML entry, or reset. Drives the targetSizeGB display
    # binding back into QML.
    targetSizeChanged = Signal()
    # Current background operation kind: "" / "unpack" / "catalog" / "pack" /
    # "probe". Lets the QML show per-stage status (e.g. "解包中…" in the image
    # card) instead of a generic busy spinner.
    currentOpChanged = Signal()
    # True once an unpack has completed successfully; reset on opening a new
    # image. Drives the "已解包" badge in the image card.
    unpackedChanged = Signal()

    # ---- modal signals (QML shows the dialog) ----
    infoMessage = Signal(str, str)        # (title, text)
    errorMessage = Signal(str, str)        # (title, text)
    guardBlocked = Signal(str, str)       # (app_name, reason)

    def __init__(self, title: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._title = title or "SystemImgKit — system.img 精简工具"
        self._image_path: str | None = None
        self._image_name: str = ""
        self._image_size: str = ""
        self._image_fmt: str = ""
        self._image_avb: str = ""
        self._image_ok: bool = False
        self._workspace_dir: str | None = None
        self._cat: catalog.Catalog | None = None
        self._worker: Worker | None = None
        self._busy = False
        self._current_op: str = ""   # "" / "unpack" / "catalog" / "pack" / "probe"
        self._unpacked: bool = False
        self._risk_override = False
        self._target_blocks: int = 0   # 0 = use original partition size
        self._warnings: list[str] = []
        # Log streaming throttle: rsync --info=progress2 emits dozens of \r
        # progress lines per second. Appending each verbatim and notifying QML
        # on every line makes the RichText log re-escape+recolor ALL history each
        # time → main thread pegged → "无响应" → crash. Two guards:
        #  (1) a \r-carrying progress line REPLACES the previous line instead of
        #      appending (progress2 rewrites one status line in place), so the
        #      log doesn't grow by thousands of near-identical lines;
        #  (2) a coalescing timer flushes warningsChanged at most every 100ms,
        #      and the log is capped (older lines dropped) to bound RichText cost.
        self._log_dirty = False
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.setInterval(100)
        self._log_flush_timer.timeout.connect(self._flush_log)
        self._LOG_MAX_LINES = 800
        self.app_model = AppCardModel(self)
        self.file_model = FileTreeModel(self)
        self.bigfile_model = BigFileModel(self)
        # Forward model selection changes to the reclaimTotal property.
        self.app_model.dataChanged.connect(lambda *_: self.reclaimChanged.emit())
        self.app_model.modelReset.connect(self.reclaimChanged)
        # Forward model-side guard refusals so QML can show a message.
        self.app_model.guardBlocked.connect(self.guardBlocked)
        # Sync app selections to the big-file model: when an app is checked,
        # big files under its directory show as checked (deleted with the app).
        self._sync_bigfiles_from_apps()
        self.app_model.dataChanged.connect(lambda *_: self._sync_bigfiles_from_apps())
        self.app_model.modelReset.connect(self._sync_bigfiles_from_apps)
        # Big-file selection changes the reclaimable total too.
        self.bigfile_model.dataChanged.connect(lambda *_: self.reclaimChanged.emit())

    # ---- properties ----

    def _image_info(self) -> str:
        # Kept for backward compat; structured fields below are preferred.
        if not self._image_name:
            return "尚未打开镜像。"
        if not self._image_ok:
            return f"{self._image_name}  ·  不支持"
        return f"{self._image_name}  ·  {self._image_size}  ·  {self._image_fmt}  ·  AVB页脚={self._image_avb}"

    imageInfo = Property(str, _image_info, notify=imageInfoChanged)

    def _img_name(self) -> str:
        return self._image_name

    imageName = Property(str, _img_name, notify=imageInfoChanged)

    def _img_size(self) -> str:
        return self._image_size

    imageSize = Property(str, _img_size, notify=imageInfoChanged)

    def _img_fmt(self) -> str:
        return self._image_fmt

    imageFmt = Property(str, _img_fmt, notify=imageInfoChanged)

    def _img_avb(self) -> str:
        return self._image_avb

    imageAvb = Property(str, _img_avb, notify=imageInfoChanged)

    def _img_ok(self) -> bool:
        return self._image_ok

    imageOk = Property(bool, _img_ok, notify=imageInfoChanged)

    def _image_dir(self) -> str:
        # Directory containing the opened image — used as the auto-unpack
        # workspace when the user picks an image (no separate workspace prompt).
        return os.path.dirname(self._image_path) if self._image_path else ""

    imageDir = Property(str, _image_dir, notify=imageInfoChanged)

    def _current_op_get(self) -> str:
        return self._current_op

    currentOp = Property(str, _current_op_get, notify=currentOpChanged)

    def _unpacked_get(self) -> bool:
        return self._unpacked

    unpacked = Property(bool, _unpacked_get, notify=unpackedChanged)

    def _title(self) -> str:
        return self._title

    windowTitle = Property(str, _title, constant=True)

    def set_title(self, title: str) -> None:
        self._title = title

    def _can_unpack(self) -> bool:
        return self._image_path is not None and not self._busy

    canUnpack = Property(bool, _can_unpack, notify=isReadyChanged)

    def _can_catalog(self) -> bool:
        return self._workspace_dir is not None and not self._busy

    canCatalog = Property(bool, _can_catalog, notify=isReadyChanged)

    def _can_pack(self) -> bool:
        return self._cat is not None and not self._busy

    canPack = Property(bool, _can_pack, notify=isReadyChanged)

    def _busy_get(self) -> bool:
        return self._busy

    progressBusy = Property(bool, _busy_get, notify=progressBusyChanged)

    def _risk_get(self) -> bool:
        return self._risk_override

    riskOverride = Property(bool, _risk_get, notify=riskOverrideChanged)

    def _reclaim(self) -> str:
        total = self.app_model.reclaim_total() + self.bigfile_model.selected_size()
        cnt = self.app_model.selected_count()
        bcnt = sum(1 for c in self.bigfile_model._checked if c)
        parts = [f"{cnt} 个应用"]
        if bcnt:
            parts.append(f"{bcnt} 个大文件")
        return f"可回收：{_human(total)}（已选 {' + '.join(parts)}）"

    reclaimTotal = Property(str, _reclaim, notify=reclaimChanged)

    def _warnings_get(self) -> list[str]:
        return self._warnings

    warnings = Property("QVariantList", _warnings_get, notify=warningsChanged)

    def _catalog_loaded(self) -> bool:
        return self._cat is not None

    catalogLoaded = Property(bool, _catalog_loaded, notify=catalogLoadedChanged)

    # target partition size in blocks (0 = use original). Lets the user build
    # a smaller image to fit a device system partition that is smaller than
    # the original image.
    def _block_size(self) -> int:
        """The image's block size, from the loaded manifest when available,
        else 4096. Used so probe/manual-entry/pack all agree on units."""
        if self._workspace_dir:
            try:
                man = manifest.Manifest.load(Workspace(self._workspace_dir).manifest)
                if man.block_size:
                    return man.block_size
            except (OSError, ValueError):
                pass
        return 4096

    def _target_blocks_get(self) -> int:
        return self._target_blocks

    def _target_blocks_set(self, v: int) -> None:
        v = int(v) if v else 0
        if v != self._target_blocks:
            self._target_blocks = v
            # Keep the QML display field in sync whenever the canonical value
            # changes — whether from a probe, manual QML entry, or reset.
            self.targetSizeChanged.emit()

    targetBlocks = Property(int, _target_blocks_get, _target_blocks_set,
                            notify=targetSizeChanged)

    def _target_size_gb(self) -> str:
        """Display the current target size in GB, derived from the canonical
        block count and the image block size (real bytes). Format mirrors the
        manual-entry convention (1 GB = 1e9 bytes); "0" means no target set."""
        if not self._target_blocks:
            return "0"
        bs = self._block_size()
        gb = self._target_blocks * bs / 1e9
        # Trim trailing zeros for a clean field (7.68 not 7.6800000000).
        s = f"{gb:.6f}".rstrip("0").rstrip(".")
        return s or "0"

    targetSizeGB = Property(str, _target_size_gb, notify=targetSizeChanged)

    def _image_block_size_get(self) -> int:
        return self._block_size()

    # Expose the image block size to QML so manual GB→blocks conversion uses
    # the real block size (manifest) instead of a hardcoded 4096, matching the
    # probe path. Re-evaluated when the workspace/manifest changes.
    imageBlockSize = Property(int, _image_block_size_get,
                              notify=catalogLoadedChanged)

    def _sections(self) -> list:
        return self.app_model.sections()

    sections = Property("QVariantList", _sections, notify=sectionsChanged)

    # models exposed to QML (read-only)
    def _app_model(self):
        return self.app_model

    appModel = Property("QVariant", _app_model, constant=True)

    def _file_model(self):
        return self.file_model

    fileModel = Property("QVariant", _file_model, constant=True)

    def _bigfile_model(self):
        return self.bigfile_model

    bigFileModel = Property("QVariant", _bigfile_model, constant=True)

    # ---- warnings helpers ----

    def append_warning(self, line: str) -> None:
        self._append_log_line(line)

    def append_warnings(self, lines) -> None:
        if isinstance(lines, str):
            lines = [lines]
        for line in lines:
            self._append_log_line(line)
        self._schedule_log_flush()

    def _append_log_line(self, line: str) -> None:
        # rsync --info=progress2 rewrites a single status line using \r
        # (carriage return, no newline) — the stderr reader splits on \n, so a
        # "line" here may carry embedded \r segments. Treat any \r-bearing line
        # as an in-place update: replace the last log line instead of appending,
        # so a long rsync run adds one rolling progress line, not thousands.
        #
        # The same mechanism carries the pack heartbeat (root_helper polls the
        # output image's real allocated bytes during the silent mke2fs -d /
        # e2fsdroid fill phase and emits a \r-prefixed line). A heartbeat line
        # replaces the prior heartbeat in place, so the whole multi-minute fill
        # is one rolling line — not hundreds of appended lines (see change
        # pack-progress-heartbeat, design D4).
        if "\r" in line:
            # keep only the segment after the last \r (the current status)
            line = line.rsplit("\r", 1)[-1]
            if self._warnings and (
                    _looks_like_progress(self._warnings[-1])
                    or _looks_like_heartbeat(self._warnings[-1])):
                self._warnings[-1] = line
            else:
                self._warnings.append(line)
        else:
            self._warnings.append(line)
        # cap the log so the RichText render stays bounded
        if len(self._warnings) > self._LOG_MAX_LINES:
            self._warnings = self._warnings[-self._LOG_MAX_LINES:]
        self._schedule_log_flush()

    def _schedule_log_flush(self) -> None:
        # Coalesce rapid progress bursts into one QML notification per 100ms.
        self._log_dirty = True
        if not self._log_flush_timer.isActive():
            self._log_flush_timer.start()

    def _flush_log(self) -> None:
        if self._log_dirty:
            self._log_dirty = False
            self.warningsChanged.emit()

    def set_startup_warnings(self, lines: list[str]) -> None:
        self._warnings = list(lines)
        self.warningsChanged.emit()

    # ---- override ----

    @Slot(bool)
    def setOverride(self, on: bool) -> None:
        """Apply risk-override (QML has already confirmed if turning on)."""
        if on == self._risk_override:
            return
        self._risk_override = on
        self.app_model.set_risk_override(on)
        self.bigfile_model.set_risk_override(on)
        self.riskOverrideChanged.emit()
        self.reclaimChanged.emit()

    # ---- operations ----

    @staticmethod
    def _local_path(url_or_path: str) -> str:
        """Normalize a file URL or plain path from a Qt dialog to a local path.

        FileDialog.currentFile / FolderDialog.currentFolder return `file:///...`
        URLs; strip the scheme so os.path / subprocess get a real path.
        """
        if not url_or_path:
            return ""
        p = url_or_path
        if p.startswith("file:"):
            from PySide6.QtCore import QUrl
            p = QUrl(p).toLocalFile() or p[5:]  # fallback: strip "file:"
        return p

    @Slot(str)
    def openImage(self, path: str) -> None:
        path = self._local_path(path)
        if not path:
            return
        self._image_path = path
        # Opening a new image invalidates any prior unpack state.
        if self._unpacked:
            self._unpacked = False
            self.unpackedChanged.emit()
        try:
            fmt, foot = imagefmt.ensure_supported(path)
            size = os.path.getsize(path)
            self._image_name = os.path.basename(path)
            self._image_size = f"{size/1e9:.2f} GB"
            self._image_fmt = fmt.value
            self._image_avb = "有" if foot is imagefmt.AvbFooterPresence.PRESENT else "无"
            self._image_ok = True
        except Exception as e:  # noqa: BLE001
            self._image_name = os.path.basename(path)
            self._image_size = ""
            self._image_fmt = ""
            self._image_avb = ""
            self._image_ok = False
            self.errorMessage.emit("不支持的镜像", str(e))
        self.imageInfoChanged.emit()
        self.isReadyChanged.emit()

    @Slot(str)
    def openImageAndUnpack(self, path: str) -> None:
        """Open an image and, if it is valid, immediately unpack it into the
        image's own directory (used as the workspace). This removes the separate
        "解包" step: picking an image starts unpacking right away. The workspace
        FolderDialog is bypassed — the image's directory IS the workspace.
        """
        self.openImage(path)
        if self._image_ok and not self._busy:
            self.doUnpack(os.path.dirname(self._image_path))

    @Slot(str)
    def doUnpack(self, ws_dir: str) -> None:
        ws_dir = self._local_path(ws_dir)
        if not self._image_path or not ws_dir:
            return
        self._workspace_dir = ws_dir
        self.append_warnings(["开始解包：将剥离 AVB 页脚并提取文件树。",
                              "（将弹出系统授权窗口，请输入密码以只读挂载）"])
        self._start_worker(
            lambda on_line, cancel: rootops.run_unpack(
                self._image_path, ws_dir, on_line=on_line, cancel=cancel),
            on_done=self._on_unpacked, op="unpack")

    def _on_unpacked(self, res) -> None:
        # res is a dict from the root helper (SIK_RESULT), or {"ok": False, ...}
        if not res.get("ok"):
            self.append_warning("错误：" + res.get("error", "解包失败"))
            self.errorMessage.emit("解包失败", res.get("error", "解包失败"))
            return
        if not self._unpacked:
            self._unpacked = True
            self.unpackedChanged.emit()
        self.append_warnings([
            f"解包完成：已剥离页脚={res.get('footer_stripped')}，"
            f"原始镜像大小={res.get('original_image_size', 0):,} 字节",
        ])
        if res.get("incomplete"):
            self.append_warnings([
                "警告：使用了无 root 降级模式 —— SELinux 上下文/能力位可能未完整"
                "捕获，元数据回写将不完整。"
            ])
        self.isReadyChanged.emit()
        # 解包成功后自动列出应用，免去手动点“列出应用”。
        self.doCatalog()

    @Slot()
    def doCatalog(self) -> None:
        if not self._workspace_dir:
            return
        ws = Workspace(self._workspace_dir)
        if not os.path.isdir(ws.tree):
            self.errorMessage.emit("尚未解包", "请先解包镜像。")
            return
        # build_catalog + the Files tree walk are expensive (thousands of
        # root-owned entries); run them on a worker thread so the UI stays
        # responsive, then apply the results on the main thread.
        tree = ws.tree
        self.append_warning("正在列出应用…")
        self._start_worker(
            lambda on_line, cancel: _build_catalog_job(tree, on_line),
            on_done=self._on_cataloged, op="catalog")

    def _sync_bigfiles_from_apps(self) -> None:
        """Push the selected apps' image_paths to the big-file model so big
        files under a selected app show as checked (will be deleted with it)."""
        self.bigfile_model.setSelectedAppPaths(
            [a.image_path for a in self.app_model.selected_apps()])

    def _on_cataloged(self, res) -> None:
        if res is None:
            self.errorMessage.emit("列出失败", "无法构建应用目录。")
            return
        cat, tree, dir_rows, big_file_rows = res
        self._cat = cat
        self.app_model.set_catalog(cat)
        self.file_model.load_rows(dir_rows, cat.protected_paths)
        self.bigfile_model.load_rows(big_file_rows)
        self.catalogLoadedChanged.emit()
        self.sectionsChanged.emit()
        self.reclaimChanged.emit()
        # canPack depends on _cat being set; re-evaluate the ready/can-* bindings
        # so the 打包 button enables after the catalog loads.
        self.isReadyChanged.emit()
        self.append_warning(f"已列出 {len(cat.apps)} 个应用。")

    @Slot(str)
    @Slot()
    def probeDevicePartition(self) -> None:
        """Probe the connected device's system_a partition size via fastboot
        and set targetBlocks so the rebuilt image fits it.

        Runs in a background Worker (never on the main thread) so the UI stays
        responsive when no device is connected. The worker does a
        `fastboot devices` preflight first; if nothing is attached it returns
        an error without ever issuing a blocking `getvar`.
        """
        if self._busy:
            return
        block_size = self._block_size()
        self.append_warning("正在探测设备分区（fastboot）…")
        self._start_worker(
            lambda on_line, cancel: _probe_job(block_size, on_line, cancel),
            on_done=self._on_probed, op="probe")

    def _on_probed(self, res) -> None:
        """Apply a probe result (from the Worker) on the main thread."""
        if res is None or not res.get("ok"):
            err = (res or {}).get("error", "探测失败")
            self.append_warning("错误：" + err)
            self.errorMessage.emit("探测失败", err)
            return
        size_bytes = res["size_bytes"]
        blocks = res["blocks"]
        self._target_blocks = blocks
        self.targetSizeChanged.emit()  # refresh the targetSizeGB display
        gb = size_bytes / 1e9
        self.append_warning(f"探测到 system_a: {size_bytes:,} 字节 = {gb:.2f} GB "
                            f"({blocks:,} 块)。已设为目标分区大小。")
        self.infoMessage.emit(
            "已探测设备分区",
            f"system_a = {gb:.2f} GB ({blocks:,} 块)。\n"
            f"目标分区大小已设为此值。\n"
            f"注意:需删够内容,使镜像 ≤ 此大小才能刷入。")

    @Slot()
    def packDefault(self) -> None:
        """Pack to a default output path (workspace/system_new.img) — no file
        dialog. The user opts out of choosing a path and just confirms."""
        if not self._workspace_dir or self._cat is None:
            self.errorMessage.emit("尚未就绪", "请先打开、解包并列出应用。")
            return
        out_path = os.path.join(self._workspace_dir, "system_new.img")
        self.packTo(out_path)

    def packTo(self, out_path: str) -> None:
        out_path = self._local_path(out_path)
        if not out_path:
            return
        if not self._workspace_dir or self._cat is None:
            self.errorMessage.emit("尚未就绪", "请先打开、解包并列出应用。")
            return
        apps = self.app_model.selected_apps()
        file_paths = self.file_model.selected_paths()
        bigfile_paths = self.bigfile_model.selected_paths()
        if bigfile_paths:
            # merge big-file deletions with the Files-view selections (dedup,
            # preserving order)
            seen = set(file_paths)
            for p in bigfile_paths:
                if p not in seen:
                    file_paths.append(p)
                    seen.add(p)
            self.append_warning(f"含 {len(bigfile_paths)} 个大文件删除项（共 {self.bigfile_model.selected_size()/1e6:.1f} MB）")
        if not apps and not file_paths:
            self.infoMessage.emit(
                "未选择任何项",
                "请勾选要删除的应用/文件，或继续以做一次往返测试。")
        override_log: list[str] = []
        try:
            deletions = catalog.select_deletions(
                self._cat,
                [a.name for a in apps],
                chosen_file_paths=file_paths,
                risk_override=self._risk_override,
                override_log=override_log,
            )
        except Exception as e:  # noqa: BLE001
            self.errorMessage.emit("选择错误", str(e))
            return
        for line in override_log:
            self.append_warning(line)
        ws = Workspace(self._workspace_dir)

        # Pre-pack fit guard (decision D4): when a target partition size is set
        # (target_blocks > 0, from probe or manual entry), estimate the
        # remaining content size and refuse to pack if it would not fit the
        # target. Cheap estimate (original content − reclaim) — the backend's
        # precise _du cap in pack.py stays the authoritative backstop. When
        # target_blocks == 0 (no target set), pack unconditionally.
        if self._target_blocks and self._target_blocks > 0:
            if not self._prepack_fit_ok(ws):
                return

        deletions_file = catalog.save_deletions(ws, deletions)
        self.append_warning(f"开始打包：将删除 {len(deletions)} 项，重建 ext4 镜像…")
        self.append_warning("（将弹出系统授权窗口，请输入密码以回写元数据）")
        tb = self._target_blocks or None
        # Look for vbmeta.img next to the source image (AVB verification must be
        # disabled when flashing a modified system, else the device orange-screens).
        vbmeta = None
        if self._image_path:
            cand = os.path.join(os.path.dirname(self._image_path), "vbmeta.img")
            if os.path.isfile(cand):
                vbmeta = cand
        self._start_worker(
            lambda on_line, cancel: rootops.run_pack(
                self._workspace_dir, out_path,
                deletions_file=deletions_file,
                target_blocks=tb,
                vbmeta=vbmeta,
                on_line=on_line, cancel=cancel),
            on_done=lambda r: self._on_packed(r, out_path), op="pack")

    def _on_packed(self, res, out_path: str) -> None:
        if not res.get("ok"):
            self.append_warning("错误：" + res.get("error", "打包失败"))
            self.errorMessage.emit("打包失败", res.get("error", "打包失败"))
            return
        self.append_warnings([
            f"打包完成 → {res.get('output_image')}",
            f"  e2fsck 校验通过={res.get('e2fsck_clean')}  "
            f"元数据已回写={res.get('metadata_restored')}",
        ])
        for w in res.get("warnings", []):
            self.append_warning("警告：" + w)
        self.infoMessage.emit(
            "打包完成",
            f"镜像已写入 {res.get('output_image')}。\n刷机脚本：{res.get('flash_script')}")

    @Slot()
    def cancelWorker(self) -> None:
        # Immediate feedback so the click is never "无反应": log the cancel
        # request at once, then signal the worker. The actual teardown (helper
        # self-terminates) follows within ~1 s.
        cancel_debug("GUI cancelWorker called")
        if self._worker:
            cancel_debug("GUI has worker, calling worker.cancel()")
            self.append_warning("正在取消…")
            self._worker.cancel()
            cancel_debug("GUI worker.cancel() returned")
        else:
            cancel_debug("GUI cancelWorker: NO worker (self._worker is None)")

    def _prepack_fit_ok(self, ws: Workspace) -> bool:
        """Cheap pre-pack fit check (decision D4). Returns True if packing may
        proceed, False (after emitting an errorMessage) if the estimated
        remaining content exceeds the target partition. Only called when
        ``self._target_blocks > 0``.

        Estimate = manifest.original_image_size − selected_reclaim. This is a
        coarse upper bound (ignores fs overhead / shared-blocks dedup); the
        backend ``pack.pack()`` precise ``_du`` cap remains the backstop.
        """
        try:
            man = manifest.Manifest.load(ws.manifest)
        except (OSError, ValueError) as e:
            # No/invalid manifest → can't estimate; let pack proceed and let
            # the backend's own cap decide (matches the no-target pass-through
            # spirit rather than blocking on a missing file).
            self.append_warning(f"无法读取 manifest 做预检（{e}），跳过大小校验。")
            return True
        block_size = man.block_size or self._block_size()
        original_content_size = man.original_image_size or 0
        reclaim = (self.app_model.reclaim_total()
                   + self.bigfile_model.selected_size())
        target_bytes = self._target_blocks * block_size
        # Target partition larger than the original image: no shrinking is
        # needed, so there is nothing to fit-check. The backend (pack.py) clamps
        # to the original size in this case; report it upfront here so the user
        # is told at click time rather than only via the mid-pack on_line. See
        # change pack-target-clamp.
        if target_bytes > original_content_size:
            self.append_warning(
                f"设备分区 {target_bytes:,} 字节大于原镜像 "
                f"{original_content_size:,} 字节，将按原镜像大小建镜像，"
                f"分区剩余空间不使用。")
            return True
        estimate_remaining = max(original_content_size - reclaim, 0)
        if estimate_remaining > target_bytes:
            self.append_warning(
                f"预检未通过：剩余内容约 {estimate_remaining:,} 字节 "
                f"> 目标分区 {target_bytes:,} 字节（已选删除 {reclaim:,} 字节）。"
            )
            self.errorMessage.emit(
                "删得不够，装不下目标分区",
                f"剩余内容约 {estimate_remaining:,} 字节，超过目标分区 "
                f"{target_bytes:,} 字节。\n请多勾选一些应用/文件再打包。"
                f"\n（已选删除 {reclaim:,} 字节）")
            return False
        self.append_warning(
            f"预检通过：剩余内容约 {estimate_remaining:,} 字节 "
            f"≤ 目标分区 {target_bytes:,} 字节。")
        return True

    # ---- worker lifecycle ----

    def _start_worker(self, fn, on_done, op: str = "") -> None:
        self._current_op = op
        self.currentOpChanged.emit()
        self._set_busy(True)
        self._worker = Worker(fn)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(lambda r: self._on_worker_done(r, on_done))
        self._worker.signals.failed.connect(self._on_worker_failed)
        self._worker.signals.cancelled.connect(self._on_worker_cancelled)
        self._worker.start()

    def _on_progress(self, line: str) -> None:
        self.append_warning("  " + line)

    def _on_worker_done(self, res, on_done) -> None:
        self._set_busy(False)
        if on_done:
            on_done(res)
        # If the on_done callback did not chain into another worker, clear the
        # current operation. (A chained op — e.g. _on_unpacked → doCatalog —
        # re-enters _start_worker and sets a new op while _busy is already True.)
        if not self._busy:
            self._current_op = ""
            self.currentOpChanged.emit()

    def _on_worker_failed(self, msg: str) -> None:
        self._set_busy(False)
        self._current_op = ""
        self.currentOpChanged.emit()
        self.append_warning("错误：" + msg)
        self.errorMessage.emit("操作失败", msg)

    def _on_worker_cancelled(self) -> None:
        self._set_busy(False)
        self._current_op = ""
        self.currentOpChanged.emit()
        self.append_warning("已取消。")

    def _set_busy(self, busy: bool) -> None:
        if self._busy == busy:
            return
        self._busy = busy
        self.progressBusyChanged.emit()
        self.isReadyChanged.emit()


def _human(n: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}P"


def _looks_like_progress(line: str) -> bool:
    """Heuristic: is `line` an rsync --info=progress2 status line that should
    be rewritten in place rather than appended? progress2 lines look like
        '    1,234,567  12%  10.00MB/s    0:01:23'
    (digits+commas, a % , and a speed/time tail). We keep it conservative so
    real log lines are never mis-collapsed.
    """
    return ("%" in line and ("/s" in line or ":" in line)
            and any(ch.isdigit() for ch in line))


def _looks_like_heartbeat(line: str) -> bool:
    """Is `line` a pack heartbeat (root_helper fill-phase watcher) that should
    roll in place? Heartbeat lines start with the `⟳` sentinel, e.g.
        '⟳ 正在构建镜像… 已写入 2.34 GB  (约 41%)'
    '⟳ 元数据回写 1200/6440'
    Conservative — only the sentinel prefix matches, so a real log line is
    never mis-collapsed (no stage/warning line starts with `⟳`).
    """
    return line.startswith(HEARTBEAT_SENTINEL)
