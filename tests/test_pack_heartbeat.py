"""Unit tests: pack heartbeat watcher + in-place log rendering + metadata
i/N progress (change pack-progress-heartbeat, tasks 4.1–4.4).

The heartbeat watcher (`root_helper._Heartbeat`) is a plain threading object
that never touches Qt; it emits via the module-level `_progress`. The
log-rendering predicates (`_looks_like_heartbeat` / `_append_log_line`) live
in the controller and need a `QApplication` to instantiate `Controller`.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from systemimgkit import root_helper
from systemimgkit.runner import HEARTBEAT_SENTINEL


# ---- 4.1 / 4.2: heartbeat watcher -------------------------------------------

def _make_file_with_blocks(path: str, nblocks: int) -> None:
    """Write a file whose `st_blocks` is ~nblocks (512B blocks) by writing
    real data (fallocate makes st_blocks reflect real allocation)."""
    if nblocks <= 0:
        open(path, "wb").close()
        return
    with open(path, "wb") as fh:
        fh.truncate(nblocks * 512)
        # write one byte per page so the FS allocates real blocks (not sparse)
        for i in range(0, nblocks * 512, 4096):
            fh.seek(i)
            fh.write(b"x")


def test_heartbeat_no_emission_when_file_missing(monkeypatch, tmp_path):
    """4.1: while the output file does not exist, no heartbeat line is emitted."""
    emitted: list[str] = []
    monkeypatch.setattr(root_helper, "_progress", emitted.append)
    missing = str(tmp_path / "nope.img")

    stop = threading.Event()
    hb = root_helper._Heartbeat(missing, target_bytes=None, stop=stop,
                                interval=0.03)
    hb.start()
    # let it poll a few times against a non-existent file
    time.sleep(0.15)
    stop.set()
    hb.join(timeout=2.0)
    assert emitted == []
    assert not hb._thread.is_alive()


def test_heartbeat_emits_increasing_bytes_and_stops(monkeypatch, tmp_path):
    """4.1: as st_blocks grows, emitted "已写入" values increase; once stop is
    set, no further lines are emitted."""
    emitted: list[str] = []
    monkeypatch.setattr(root_helper, "_progress", emitted.append)
    out = str(tmp_path / "grow.img")
    open(out, "wb").close()  # start empty (st_blocks ~ 0)

    stop = threading.Event()
    hb = root_helper._Heartbeat(out, target_bytes=None, stop=stop,
                                interval=0.05)
    hb.start()
    # grow the file's real allocation across a few ticks
    for nb in (2000, 8000, 20000):
        time.sleep(0.08)
        _make_file_with_blocks(out, nb)
    time.sleep(0.08)
    stop.set()
    hb.join(timeout=2.0)
    assert not hb._thread.is_alive()

    assert len(emitted) >= 2
    # every line carries the sentinel and the rolling prefix (after the \r)
    assert all(ln.lstrip("\r").startswith("⟳ 正在构建镜像… 已写入 ") for ln in emitted)
    # bytes-only form (target_bytes=None) → no percentage
    assert all("约" not in ln for ln in emitted)
    # extract the GB values and confirm they are non-decreasing
    vals = []
    for ln in emitted:
        gb = float(ln.split("已写入 ")[1].split(" GB")[0])
        vals.append(gb)
    assert vals == sorted(vals)
    assert vals[-1] > vals[0]


def test_heartbeat_approximate_percentage_when_target_known(monkeypatch, tmp_path):
    """4.2: with target_bytes known, the percentage is st_blocks*512/target_bytes."""
    emitted: list[str] = []
    monkeypatch.setattr(root_helper, "_progress", emitted.append)
    out = str(tmp_path / "pct.img")
    open(out, "wb").close()

    target_bytes = 100 * 1024 * 1024  # 100 MiB ceiling
    stop = threading.Event()
    hb = root_helper._Heartbeat(out, target_bytes=target_bytes, stop=stop,
                                interval=0.03)
    hb.start()
    # allocate ~25 MiB of real blocks → expect ~25%
    _make_file_with_blocks(out, (25 * 1024 * 1024) // 512)
    time.sleep(0.08)
    stop.set()
    hb.join(timeout=2.0)
    assert emitted
    last = emitted[-1]
    assert "约" in last
    pct = float(last.split("约 ")[1].rstrip("%)"))
    # expect roughly 25% (allow FS overhead slop)
    assert 15.0 <= pct <= 35.0


def test_heartbeat_bytes_only_when_target_none(monkeypatch, tmp_path):
    """4.2: when target_bytes is None (manifest unavailable), no percentage."""
    emitted: list[str] = []
    monkeypatch.setattr(root_helper, "_progress", emitted.append)
    out = str(tmp_path / "none.img")
    _make_file_with_blocks(out, 4000)
    stop = threading.Event()
    hb = root_helper._Heartbeat(out, target_bytes=None, stop=stop,
                                interval=0.02)
    hb.start()
    time.sleep(0.08)
    stop.set()
    hb.join(timeout=2.0)
    assert emitted
    assert all("约" not in ln for ln in emitted)
    assert all(ln.lstrip("\r").startswith(HEARTBEAT_SENTINEL) for ln in emitted)


# ---- 4.3: in-place log rendering (needs Qt) ---------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_looks_like_heartbeat_predicate():
    """4.3: _looks_like_heartbeat matches ⟳-prefixed lines, not real logs."""
    from systemimgkit.gui.controller import _looks_like_heartbeat
    assert _looks_like_heartbeat("⟳ 正在构建镜像… 已写入 2.34 GB  (约 41%)")
    assert _looks_like_heartbeat("⟳ 元数据回写 1200/6440")
    assert not _looks_like_heartbeat("mke2fs -d (block_size=4096, blocks=2786222)…")
    assert not _looks_like_heartbeat("e2fsck -fy …")
    assert not _looks_like_heartbeat("")


def test_log_heartbeat_replaces_prior_heartbeat(qapp):
    """4.3: an incoming heartbeat replaces a prior heartbeat in place — the
    whole fill phase is one rolling line, not appended per tick."""
    from systemimgkit.gui.controller import Controller
    c = Controller()
    c._warnings = []
    c.append_warning("mke2fs -d (block_size=4096, blocks=2786222)…")
    before = len(c._warnings)
    # simulate a stream of heartbeat ticks (each carries \r)
    for gb in (0.10, 0.20, 0.30, 0.40):
        c.append_warning(f"\r⟳ 正在构建镜像… 已写入 {gb:.2f} GB  (约 3%)")
    after = len(c._warnings)
    assert after == before + 1, "heartbeat ticks must roll in place, not append"
    assert c._warnings[-1].startswith("⟳ 正在构建镜像… 已写入 0.40 GB")


def test_log_real_line_after_heartbeat_appends(qapp):
    """4.3: a normal log line following a heartbeat appends (not collapsed)."""
    from systemimgkit.gui.controller import Controller
    c = Controller()
    c._warnings = []
    c.append_warning("\r⟳ 正在构建镜像… 已写入 1.00 GB  (约 9%)")
    c.append_warning("restoring metadata (uid/gid/xattrs/caps/mtime)…")
    assert len(c._warnings) == 2
    assert c._warnings[-1].startswith("restoring metadata")


def test_log_rsync_progress_still_rolls(qapp):
    """4.3: the existing rsync progress2 in-place rule is unchanged."""
    from systemimgkit.gui.controller import Controller
    c = Controller()
    c._warnings = []
    c.append_warning("\r    1,234,567  12%  10.00MB/s    0:01:23")
    c.append_warning("\r    2,000,000  19%  10.00MB/s    0:01:30")
    assert len(c._warnings) == 1


def test_log_metadata_heartbeat_replaces_prior(qapp):
    """4.3: metadata i/N heartbeat rolls in place like the build heartbeat."""
    from systemimgkit.gui.controller import Controller
    c = Controller()
    c._warnings = []
    c.append_warning("restoring metadata (uid/gid/xattrs/caps/mtime)…")
    base = len(c._warnings)
    c.append_warning("\r⟳ 元数据回写 1000/6440")
    c.append_warning("\r⟳ 元数据回写 2000/6440")
    c.append_warning("\r⟳ 元数据回写 3000/6440")
    assert len(c._warnings) == base + 1
    assert "3000/6440" in c._warnings[-1]


# ---- 4.4: metadata restore i/N granularity ----------------------------------

def test_restore_metadata_emits_in_heartbeat_granularity(monkeypatch, tmp_path):
    """4.4: _restore_metadata emits `⟳ 元数据回写 i/N` at the 1000-entry
    granularity (and a final count), not per-entry. The mount is stubbed so no
    root is needed."""
    import contextlib
    from systemimgkit import pack as _pack
    from systemimgkit.manifest import Manifest, FileEntry

    # stub loop_mount to yield a temp dir (no real mount/root). _restore_metadata
    # imports loop_mount lazily from .mountutil, so patch it there.
    @contextlib.contextmanager
    def fake_mount(image_path, *, read_only=False, on_line=None, cancel=None):
        yield str(tmp_path)
    import systemimgkit.mountutil as mu
    monkeypatch.setattr(mu, "loop_mount", fake_mount)

    entries = []
    for i in range(2500):
        entries.append(FileEntry(relpath=f"/f{i}", type="file", mode=0o644,
                                 uid=0, gid=0, mtime=0.0, size=0))
    man = Manifest(entries=entries, block_size=4096, block_count=1)

    lines: list[str] = []
    _pack._restore_metadata(str(tmp_path / "img"), man, on_line=lines.append,
                            cancel=None)

    hb = [ln for ln in lines if ln.lstrip("\r").startswith(HEARTBEAT_SENTINEL)]
    # 2500 entries, granularity 1000 → updates at 1000, 2000, and a final 2500
    assert any("1000/2500" in ln for ln in hb)
    assert any("2000/2500" in ln for ln in hb)
    assert any("2500/2500" in ln for ln in hb)
    # not per-entry: far fewer heartbeat lines than entries
    assert len(hb) < 10
