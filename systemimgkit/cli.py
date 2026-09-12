"""Command-line interface.

Tasks 6.1 (unpack), 6.2 (catalog), 6.3 (pack), 6.4 (deps-check + precheck).

Mirrors the GUI actions so the pipeline is scriptable and testable headless.
Uses stdlib argparse (no click/typer dependency needed).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

from . import avb, catalog, imagefmt, pack, tools, unpack
from .errors import SystemImgKitError
from .runner import CancelToken
from .workspace import Workspace


def _on_line(line: str) -> None:
    print("  " + line, flush=True)


def _on_line_progress(line: str) -> None:
    # rsync --info=progress2 prints \r-delimited progress; show inline.
    print("\r  " + line[:120], end="", flush=True)
    if line.endswith("\n") or "exit" in line.lower():
        print()


def cmd_check_tools(args) -> int:
    report = tools.check_tools()
    print(report.summary())
    if args.verbose:
        print("\nAvailable:")
        for name, path in sorted(report.available.items()):
            print(f"  {name}: {path}")
    return 0 if report.ok else 1


def cmd_unpack(args) -> int:
    tools.require_tools()
    cancel = CancelToken()
    try:
        res = unpack.unpack(
            args.image, args.workspace,
            on_line=_on_line, cancel=cancel,
            allow_rootless=not args.require_root,
        )
    except SystemImgKitError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"\nUnpack complete.")
    print(f"  footer_stripped: {res.footer_stripped}")
    print(f"  original_image_size: {res.original_image_size:,} bytes")
    print(f"  incomplete (rootless): {res.incomplete}")
    print(f"  workspace: {res.workspace.root}")
    return 0


def cmd_catalog(args) -> int:
    ws = Workspace(root=args.workspace)
    if not os.path.isdir(ws.tree):
        print(f"ERROR: workspace tree not found: {ws.tree}", file=sys.stderr)
        print("Run 'unpack' first.", file=sys.stderr)
        return 2
    guard = catalog.GuardList.default()
    cat = catalog.build_catalog(ws.tree, guard)
    if args.json:
        out = {
            "apps": [
                {
                    "name": a.name, "partition": a.partition, "privilege": a.privilege,
                    "image_path": a.image_path, "size": a.size,
                    "file_count": a.file_count, "guard": a.guard.value,
                }
                for a in cat.apps
            ],
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    # --list (default)
    if not args.json and not args.list:
        args.list = True
    if args.list:
        print(f"{'NAME':40} {'PARTITION':12} {'PRIV':9} {'GUARD':8} {'SIZE':>12}")
        print("-" * 85)
        total = 0
        for a in sorted(cat.apps, key=lambda x: (x.partition, x.privilege, x.name)):
            sz = _human(a.size)
            total += a.size
            print(f"{a.name[:40]:40} {a.partition:12} {a.privilege:9} "
                  f"{a.guard.value:8} {sz:>12}")
        print("-" * 85)
        print(f"{'TOTAL':40} {'':12} {'':9} {'':8} {_human(total):>12}")
        print(f"\nGuarded (overridable): {len(guard.guarded)} | "
              f"Core (locked): {len(guard.core)} | "
              f"Protected paths: {len(guard.protected_paths)}")
    return 0


def cmd_pack(args) -> int:
    tools.require_tools()
    ws = Workspace(root=args.workspace)
    if not os.path.isdir(ws.tree):
        print(f"ERROR: workspace tree not found: {ws.tree}", file=sys.stderr)
        return 2
    cancel = CancelToken()
    try:
        res = pack.pack(
            ws, args.out,
            deletions_file=args.deletions,
            sparse=args.sparse,
            vbmeta_image=args.vbmeta,
            on_line=_on_line, cancel=cancel,
        )
    except SystemImgKitError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print("\nPack complete.")
    print(f"  output: {res.output_image}")
    if res.sparse_image:
        print(f"  sparse:  {res.sparse_image}")
    print(f"  flash:   {res.flash_script}")
    print(f"  e2fsck_clean: {res.e2fsck_clean}")
    print(f"  metadata_restored: {res.metadata_restored}")
    for w in res.warnings:
        print(f"  WARNING: {w}")
    return 0


def cmd_gui(args) -> int:
    try:
        from .gui import run_gui
    except ImportError as e:
        print(f"ERROR: PySide6 is required for the GUI: {e}\n"
              "Install with: pip install PySide6", file=sys.stderr)
        return 2
    return run_gui(args)


# ── icon / shell integration ────────────────────────────────────────────
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256)


def _user_data_root() -> str:
    """Per-user data dir (XDG_DATA_HOME or ~/.local/share). No root needed."""
    return os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")


def cmd_install_icons(args) -> int:
    """Install the .desktop entry + hicolor icons into the user data dir."""
    dest_root = args.prefix if args.prefix else _user_data_root()
    apps_dir = os.path.join(dest_root, "applications")
    icon_base = os.path.join(dest_root, "icons", "hicolor")

    installed = []
    # .desktop entry
    desktop_src = os.path.join(_DATA_DIR, "systemimgkit.desktop")
    if not os.path.isfile(desktop_src):
        print(f"ERROR: missing bundled desktop file: {desktop_src}", file=sys.stderr)
        return 2
    os.makedirs(apps_dir, exist_ok=True)
    desktop_dst = os.path.join(apps_dir, "systemimgkit.desktop")
    _copy_file(desktop_src, desktop_dst)
    installed.append(desktop_dst)

    # hicolor PNGs
    for sz in _ICON_SIZES:
        src = os.path.join(_DATA_DIR, "icons", "hicolor",
                           f"{sz}x{sz}", "apps", "systemimgkit.png")
        if not os.path.isfile(src):
            print(f"WARNING: missing icon {src}", file=sys.stderr)
            continue
        dst_dir = os.path.join(icon_base, f"{sz}x{sz}", "apps")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, "systemimgkit.png")
        _copy_file(src, dst)
        installed.append(dst)

    # Also drop the SVG as a scalable source (best rendering in modern docks).
    svg_src = os.path.join(os.path.dirname(_DATA_DIR), "gui", "resources", "icon.svg")
    if os.path.isfile(svg_src):
        scalable_dir = os.path.join(icon_base, "scalable", "apps")
        os.makedirs(scalable_dir, exist_ok=True)
        dst = os.path.join(scalable_dir, "systemimgkit.svg")
        _copy_file(svg_src, dst)
        installed.append(dst)

    print(f"Installed {len(installed)} file(s) under {dest_root}:")
    for p in installed:
        print(f"  {p}")
    print("\nUpdate the menu cache with:  gtk-update-icon-cache -f "
          f"{icon_base}  (optional)")
    print("Launch from a menu with the SystemImgKit entry, or:  gtk-launch "
          "systemimgkit")
    if not args.prefix and not shutil.which("systemimgkit"):
        print("\nNOTE: 'systemimgkit' is not on PATH; the .desktop entry's "
              "Exec= will not launch until the console script is on PATH.",
              file=sys.stderr)
    return 0


def _copy_file(src: str, dst: str) -> None:
    shutil.copyfile(src, dst)


def _human(n: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}P"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="systemimgkit",
        description="Unpack, debloat, and repack Android system-as-root ext4 images.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("check-tools", help="probe for required external tools")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_check_tools)

    sp = sub.add_parser("unpack", help="unpack a system.img into a workspace")
    sp.add_argument("image", help="path to system.img")
    sp.add_argument("-w", "--workspace", required=True, help="workspace output dir")
    sp.add_argument("--require-root", action="store_true",
                    help="fail if the read-only mount cannot be done as root "
                         "(disables the rootless fallback)")
    sp.set_defaults(func=cmd_unpack)

    sp = sub.add_parser("catalog", help="list apps in an unpacked workspace")
    sp.add_argument("-w", "--workspace", required=True, help="workspace dir")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--list", action="store_true", help="print a human-readable table")
    g.add_argument("--json", action="store_true", help="print JSON")
    sp.set_defaults(func=cmd_catalog)

    sp = sub.add_parser("pack", help="rebuild a flashable image from a workspace")
    sp.add_argument("-w", "--workspace", required=True, help="workspace dir")
    sp.add_argument("--deletions", help="file of image-relative paths to delete (one per line)")
    sp.add_argument("-o", "--out", required=True, help="output image path")
    sp.add_argument("--sparse", action="store_true", help="also emit a sparse image")
    sp.add_argument("--vbmeta", help="path to the original vbmeta.img (for flash.sh)")
    sp.set_defaults(func=cmd_pack)

    sp = sub.add_parser("gui", help="启动 PySide6 桌面 GUI")
    sp.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    sp.add_argument("--orig-uid", type=int, default=None, help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_gui)

    sp = sub.add_parser(
        "install-icons",
        help="install the .desktop entry + hicolor icons into the user data dir "
             "(~/.local/share by default; no root needed)",
    )
    sp.add_argument("--prefix", default=None,
                    help="data dir prefix instead of ~/.local/share "
                         "(e.g. /usr/share for a system install)")
    sp.set_defaults(func=cmd_install_icons)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
