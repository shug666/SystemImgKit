"""Unit tests: catalog guard-list enforcement + deletion-set recording (Task 8.1)."""

import pytest

from systemimgkit import catalog
from systemimgkit.errors import GuardViolationError
from systemimgkit.workspace import Workspace


def _make_tree(tmp_path):
    """Build a tiny extracted tree with a deletable + a core + a guarded app."""
    tree = tmp_path / "tree"
    # deletable app in /system/app
    yt = tree / "system" / "app" / "YouTube"
    yt.mkdir(parents=True)
    (yt / "base.apk").write_bytes(b"x" * 1024)
    # core app in /product/priv-app
    gms = tree / "product" / "priv-app" / "GmsCore"
    gms.mkdir(parents=True)
    (gms / "base.apk").write_bytes(b"y" * 1024)
    # guarded app in /product/priv-app
    ps = tree / "product" / "priv-app" / "Phonesky"
    ps.mkdir(parents=True)
    (ps / "base.apk").write_bytes(b"z" * 1024)
    # bloat app in /system/preinstall (ZUI bundled-app dir)
    ig = tree / "system" / "preinstall" / "Instagram"
    ig.mkdir(parents=True)
    (ig / "base.apk").write_bytes(b"ig" * 1024)
    return tree


def test_build_catalog_tags_guard_levels(tmp_path):
    tree = _make_tree(tmp_path)
    cat = catalog.build_catalog(str(tree))
    names = {a.name: a.guard for a in cat.apps}
    assert names["YouTube"] is catalog.GuardLevel.NONE
    assert names["GmsCore"] is catalog.GuardLevel.CORE
    assert names["Phonesky"] is catalog.GuardLevel.GUARDED


def test_select_deletions_free_app_ok(tmp_path):
    tree = _make_tree(tmp_path)
    cat = catalog.build_catalog(str(tree))
    dels = catalog.select_deletions(cat, ["YouTube"])
    assert dels == ["/system/app/YouTube"]


def test_select_deletions_core_rejected(tmp_path):
    tree = _make_tree(tmp_path)
    cat = catalog.build_catalog(str(tree))
    with pytest.raises(GuardViolationError):
        catalog.select_deletions(cat, ["GmsCore"])


def test_select_deletions_guarded_requires_override(tmp_path):
    tree = _make_tree(tmp_path)
    cat = catalog.build_catalog(str(tree))
    with pytest.raises(GuardViolationError):
        catalog.select_deletions(cat, ["Phonesky"])
    log = []
    dels = catalog.select_deletions(cat, ["Phonesky"], risk_override=True,
                                    override_log=log)
    assert dels == ["/product/priv-app/Phonesky"]
    assert log and "Phonesky" in log[0]


def test_select_deletions_core_rejected_even_with_override(tmp_path):
    tree = _make_tree(tmp_path)
    cat = catalog.build_catalog(str(tree))
    with pytest.raises(GuardViolationError):
        catalog.select_deletions(cat, ["GmsCore"], risk_override=True)


def test_select_deletions_protected_path_rejected(tmp_path):
    tree = _make_tree(tmp_path)
    cat = catalog.build_catalog(str(tree))
    with pytest.raises(GuardViolationError):
        catalog.select_deletions(cat, [], chosen_file_paths=["/apex/foo"],
                                  risk_override=True)


def test_deletion_set_save_load_roundtrip(tmp_path):
    ws = Workspace(root=str(tmp_path / "ws"))
    import os
    os.makedirs(ws.root, exist_ok=True)
    dels = ["/system/app/Foo", "/product/app/Bar"]
    catalog.save_deletions(ws, dels)
    loaded = catalog.load_deletions(ws.deletions)
    assert loaded == dels


def test_filter_by_partition_and_query(tmp_path):
    tree = _make_tree(tmp_path)
    cat = catalog.build_catalog(str(tree))
    assert all(a.partition == "product" for a in cat.filter(partition="product"))
    assert any(a.name == "YouTube" for a in cat.filter(query="you"))


def test_preinstall_directory_scanned(tmp_path):
    """ZUI's /system/preinstall must be scanned (primary bloat location)."""
    tree = _make_tree(tmp_path)
    cat = catalog.build_catalog(str(tree))
    ig = [a for a in cat.apps if a.name == "Instagram"]
    assert len(ig) == 1
    assert ig[0].partition == "system"
    assert ig[0].privilege == "preinstall"
    assert ig[0].guard is catalog.GuardLevel.NONE  # bloat, freely deletable
