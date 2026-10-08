#!/usr/bin/env python3
"""Build the Windows package: the Rainmeter skin as dist/ai-session-usage-<version>.rmskin, plus its SHA-256.

An .rmskin is a zip that Rainmeter's Skin Installer opens: ``RMSKIN.ini`` (name, author, version, what to load)
and ``Skins/<name>/...``; after the zip comes a 16-byte footer the installer checks, the zip's length as a
little-endian int64, one zero flags byte and ``RMSKIN`` with its terminator (Rainmeter's
Library/DialogPackage.cpp and DialogInstall.cpp). The skin's files come from rainmeter/AiSessionUsage/, and the
helper from src/contents/code/ (the one copy, the same files the Plasma widget runs), into @Resources/code/.
Reproducible like the .plasmoid: entries sorted, one timestamp, stored uncompressed, the version from
src/metadata.json. Refuses compiled Python in the tree.

Usage: build_rmskin.py [--out DIR]    (default: dist/)
Prints the two paths it wrote, one per line; exit 1 with a message on any refusal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path

NAME = "ai-session-usage"
SKIN = "AiSessionUsage"
ROOT = Path(__file__).resolve().parent.parent
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o644 << 16
FOOTER_KEY = b"RMSKIN\0"


def version_of() -> str:
    """The package version, read from src/metadata.json (the one place it is written)."""
    return str(json.loads((ROOT / "src/metadata.json").read_text(encoding="utf-8"))["KPlugin"]["Version"])


def entries() -> list[tuple[str, Path]]:
    """
    Every file of the package as ``(path in the zip, file)``, sorted by the zip path.

    Raises:
        SystemExit: compiled Python in either tree, or the skin's ini missing.
    """
    skin_dir = ROOT / "rainmeter" / SKIN
    code_dir = ROOT / "src/contents/code"
    found: list[tuple[str, Path]] = []
    for path in skin_dir.rglob("*"):
        if path.is_file():
            found.append((f"Skins/{SKIN}/{path.relative_to(skin_dir).as_posix()}", path))
    for path in code_dir.glob("*.py"):
        found.append((f"Skins/{SKIN}/@Resources/code/{path.name}", path))
    compiled = [p for _, p in found if "__pycache__" in p.parts or p.suffix == ".pyc"]
    if compiled or list(code_dir.glob("**/*.pyc")):
        raise SystemExit("refusing to pack compiled Python: delete __pycache__ first")
    if not (skin_dir / f"{SKIN}.ini").is_file():
        raise SystemExit(f"no {SKIN}.ini in {skin_dir}")
    return sorted(found)


def rmskin_ini(version: str) -> str:
    """The installer's manifest (CRLF, as Rainmeter writes it)."""
    lines = ["[rmskin]", f"Name={NAME}", "Author=chaybits", f"Version={version}", "LoadType=Skin",
             f"Load={SKIN}\\{SKIN}.ini", "MinimumRainmeter=4.5.17", "MinimumWindows=10.0"]
    return "\r\n".join(lines) + "\r\n"


def build(out: Path) -> tuple[Path, Path]:
    """
    Write the package and its checksum file.

    Args:
        out: The folder to write into (created).

    Returns:
        ``(rmskin, checksum)``: the package, and a one-line file in ``sha256sum -c`` form.
    """
    version = version_of()
    files = entries()
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{NAME}-{version}.rmskin"
    with zipfile.ZipFile(target, "w") as archive:
        info = zipfile.ZipInfo("RMSKIN.ini", date_time=FIXED_TIME)
        info.compress_type = zipfile.ZIP_STORED
        info.external_attr = FILE_MODE
        archive.writestr(info, rmskin_ini(version).encode("utf-8"))
        for name, path in files:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = FILE_MODE
            archive.writestr(info, path.read_bytes())
    zip_size = target.stat().st_size
    with target.open("ab") as f:
        f.write(struct.pack("<q", zip_size) + b"\0" + FOOTER_KEY)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    checksum = out / f"{target.name}.sha256"
    checksum.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return target, checksum


def main(argv: list[str]) -> None:
    """Build from the command line and print the two paths."""
    parser = argparse.ArgumentParser(description="Build the .rmskin package and its SHA-256 file.")
    parser.add_argument("--out", type=Path, default=ROOT / "dist", help="where to write (default: dist/)")
    args = parser.parse_args(argv)
    for path in build(args.out.resolve()):
        print(path)


if __name__ == "__main__":
    main(sys.argv[1:])
