#!/usr/bin/env python3
"""Build the installable package: src/ zipped as dist/ai-session-usage-<version>.plasmoid, plus its SHA-256.

A .plasmoid is a zip with metadata.json at its root, what ``kpackagetool6 --type Plasma/Applet --install`` and the
KDE Store take. The version comes from src/metadata.json, the one place it is written. The zip is reproducible:
entries sorted, one fixed timestamp, plain-file permissions, so the same tree gives the same bytes on any
machine, and a downloaded package can be compared with a local build. It refuses to pack a ``__pycache__`` or a
``.pyc``: a compiled module holds the path it was compiled at.

Usage: build_plasmoid.py [--src DIR] [--out DIR]    (defaults: the src/ beside this script's folder, dist/)
Prints the two paths it wrote, one per line; exit 1 with a message on any refusal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

NAME = "ai-session-usage"
ROOT = Path(__file__).resolve().parent.parent
# The zip format's own epoch; one date for every entry is what makes two builds of one tree byte-identical.
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
# A plain file: the helper is always run as ``python3 <file>``, never executed directly.
FILE_MODE = 0o644 << 16


def version_of(src: Path) -> str:
    """
    Read the package version.

    Args:
        src: The package folder (holds ``metadata.json``).

    Returns:
        ``KPlugin.Version`` of ``metadata.json``.
    """
    return str(json.loads((src / "metadata.json").read_text(encoding="utf-8"))["KPlugin"]["Version"])


def package_files(src: Path) -> list[Path]:
    """
    List every file of the package, sorted by its path inside the package.

    Args:
        src: The package folder.

    Returns:
        The files, in a fixed order.

    Raises:
        SystemExit: A ``__pycache__`` folder or a ``.pyc`` file is in the tree (it would carry the build
            machine's paths), or ``metadata.json`` is missing at the root (Plasma would refuse the package).
    """
    files = sorted(p for p in src.rglob("*") if p.is_file())
    compiled = [p.relative_to(src).as_posix() for p in files if "__pycache__" in p.parts or p.suffix == ".pyc"]
    if compiled:
        raise SystemExit(f"refusing to pack compiled Python ({compiled[0]}): delete __pycache__ first")
    if not (src / "metadata.json").is_file():
        raise SystemExit(f"no metadata.json at the root of {src}")
    return files


def build(src: Path, out: Path) -> tuple[Path, Path]:
    """
    Write the package and its checksum file.

    Args:
        src: The package folder.
        out: The folder to write into (created).

    Returns:
        ``(plasmoid, checksum)``: the package, and a one-line file in ``sha256sum -c`` form.
    """
    version = version_of(src)
    files = package_files(src)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{NAME}-{version}.plasmoid"
    with zipfile.ZipFile(target, "w") as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(src).as_posix(), date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = FILE_MODE
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    checksum = out / f"{target.name}.sha256"
    checksum.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return target, checksum


def main(argv: list[str]) -> None:
    """Build from the command line and print the two paths."""
    parser = argparse.ArgumentParser(description="Build the .plasmoid package and its SHA-256 file.")
    parser.add_argument("--src", type=Path, default=ROOT / "src", help="the package folder (default: src/)")
    parser.add_argument("--out", type=Path, default=ROOT / "dist", help="where to write (default: dist/)")
    args = parser.parse_args(argv)
    for path in build(args.src.resolve(), args.out.resolve()):
        print(path)


if __name__ == "__main__":
    main(sys.argv[1:])
