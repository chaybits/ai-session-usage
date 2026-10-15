#!/usr/bin/env python3
"""Build the Widgets Board package (MSIX) of AI Session Usage, or only stage what it carries.

Two steps. **Staging** (any platform): Python's embeddable package for Windows (python.org's zip, downloaded once into
``build/widgets-board/downloads/`` and checked against its published SHA-256 every time) is unpacked into
``build/widgets-board/stage/python/``, its ``._pth`` rewritten to also search ``..\\code``; the helper is copied from
``src/contents/code/`` (one copy of the logic, H6) with ``src/metadata.json`` beside it into ``stage/code/``. The
provider project takes both folders from there. **Building** (Windows only): MSBuild restores and builds
``widgets-board/AiSessionUsage/AiSessionUsage.csproj`` with the package generated, either for the Store (an unsigned
``.msixupload``, which the Store signs) or for sideloading (a ``.msix`` signed with a given certificate, for the test
VM); the result lands in ``dist/`` as ``ai-session-usage-<version>-x64.msixupload`` or ``.msix``, each with a
``.sha256`` file.

The version is read from ``src/metadata.json``; ``Package.appxmanifest`` must carry it with a fourth part of 0, or the
build refuses (every version carrier agrees, L2).

Usage:
  build_msix.py --stage-only
  build_msix.py --store [--out DIR]
  build_msix.py --sideload CERT.pfx [--password PW] [--out DIR]
  options: --configuration Release|Debug, --msbuild PATH, --python-zip PATH (a zip already downloaded)
Prints one line per step; details of a failed MSBuild run are in logs/build_msix.log.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_CODE = ROOT / "src" / "contents" / "code"
METADATA = ROOT / "src" / "metadata.json"
PROJECT_DIR = ROOT / "widgets-board" / "AiSessionUsage"
PROJECT = PROJECT_DIR / "AiSessionUsage.csproj"
MANIFEST = PROJECT_DIR / "Package.appxmanifest"
BUILD_DIR = ROOT / "build" / "widgets-board"
STAGE_DIR = BUILD_DIR / "stage"
DOWNLOADS = BUILD_DIR / "downloads"
LOG = ROOT / "logs" / "build_msix.log"

# python.org's "Windows embeddable package (64-bit)" of 3.13.16 (2026-09-30), its SHA-256 from the release page.
PYTHON_VERSION = "3.13.16"
PYTHON_TAG = "python313"
PYTHON_ZIP_NAME = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ZIP_NAME}"
PYTHON_SHA256 = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297"
# The search paths the embedded interpreter gets: its stdlib zip, its own folder, and the helper's folder.
PTH_LINES = (f"{PYTHON_TAG}.zip", ".", "..\\code")


def package_version() -> str:
    """The version in ``src/metadata.json``, the one place it is written."""
    return str(json.loads(METADATA.read_text(encoding="utf-8"))["KPlugin"]["Version"])


def manifest_version(manifest: Path | None = None) -> str:
    """The ``Version`` of the package manifest's Identity element (``MANIFEST`` when none is given)."""
    manifest = MANIFEST if manifest is None else manifest
    match = re.search(r'<Identity\b[^>]*\bVersion="([^"]+)"', manifest.read_text(encoding="utf-8"), re.S)
    if not match:
        raise ValueError(f"{manifest}: no Identity Version")
    return match.group(1)


def check_versions() -> str:
    """Refuse a manifest whose version is not the program's with a fourth part of 0; return the program's."""
    version = package_version()
    expected = f"{version}.0"
    found = manifest_version()
    if found != expected:
        raise ValueError(f"Package.appxmanifest says {found}, metadata.json says {version}: the manifest must say {expected}")
    return version


def sha256_of(path: Path) -> str:
    """The file's SHA-256, lowercase hex."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_python_zip(downloads: Path = DOWNLOADS, url: str = PYTHON_URL, name: str = PYTHON_ZIP_NAME,
                      sha256: str = PYTHON_SHA256) -> Path:
    """Download the embeddable package once; verify its checksum every time; return its path."""
    downloads.mkdir(parents=True, exist_ok=True)
    target = downloads / name
    if not target.is_file():
        tmp = target.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as out:
            shutil.copyfileobj(response, out)
        tmp.replace(target)
    found = sha256_of(target)
    if found != sha256:
        target.unlink()
        raise ValueError(f"{name}: SHA-256 {found}, expected {sha256}; the file was deleted")
    return target


def stage(stage_dir: Path, python_zip: Path, python_sha256: str, code_src: Path = SRC_CODE,
          metadata: Path = METADATA, pth_lines: tuple[str, ...] = PTH_LINES) -> dict:
    """
    Fill ``stage_dir`` from scratch: ``python/`` from the zip, ``code/`` from the helper's folder.

    Args:
        stage_dir: Wiped and rebuilt.
        python_zip: The embeddable package; its SHA-256 must equal ``python_sha256``.
        python_sha256: The expected checksum (checked here too, so a test can pass a zip of its own).
        code_src: The helper's folder; its top-level ``.py`` files are copied, nothing else (no bytecode).
        metadata: Copied beside the helper, so ``usage_common.package_version`` reads it there.
        pth_lines: The interpreter's search paths, written as ``<tag>._pth``.

    Returns:
        A summary dict, also written as ``stage_dir/STAGE.json``.
    """
    found = sha256_of(python_zip)
    if found != python_sha256:
        raise ValueError(f"{python_zip.name}: SHA-256 {found}, expected {python_sha256}")
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    python_dir = stage_dir / "python"
    code_dir = stage_dir / "code"
    python_dir.mkdir(parents=True)
    code_dir.mkdir()
    with zipfile.ZipFile(python_zip) as zf:
        for info in zf.infolist():
            name = Path(info.filename)
            if info.is_dir() or name.is_absolute() or ".." in name.parts:
                continue
            zf.extract(info, python_dir)
    pth = next(python_dir.glob("*._pth"), None)
    if pth is None:
        raise ValueError(f"{python_zip.name}: no ._pth file inside; not an embeddable package")
    pth.write_text("\n".join(pth_lines) + "\n", encoding="ascii", newline="\r\n")
    helper = sorted(p for p in code_src.glob("*.py") if p.is_file())
    if not any(p.name == "fetch_usage.py" for p in helper):
        raise ValueError(f"{code_src}: no fetch_usage.py")
    for p in helper:
        shutil.copyfile(p, code_dir / p.name)
    shutil.copyfile(metadata, code_dir / "metadata.json")
    summary = {
        "version": str(json.loads(metadata.read_text(encoding="utf-8"))["KPlugin"]["Version"]),
        "python_zip": python_zip.name,
        "python_sha256": python_sha256,
        "pth": pth.name,
        "helper": [p.name for p in helper],
    }
    (stage_dir / "STAGE.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def find_msbuild(given: str | None) -> Path:
    """MSBuild.exe: the given path, else the newest Visual Studio or Build Tools through vswhere."""
    if given:
        return Path(given)
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    if not vswhere.is_file():
        raise FileNotFoundError("vswhere.exe not found: give --msbuild")
    out = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.Component.MSBuild",
                          "-find", r"MSBuild\**\Bin\MSBuild.exe"], capture_output=True, text=True, check=True).stdout
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        raise FileNotFoundError("no MSBuild found by vswhere: give --msbuild")
    return Path(lines[0])


def msbuild(msbuild_exe: Path, version: str, configuration: str, store: bool, pfx: Path | None,
            password: str | None) -> list[Path]:
    """Restore and build the project with the package generated (the assembly version set to ``version``); return the package files produced."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    package_dir = BUILD_DIR / "packages"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    common = [f"/p:Configuration={configuration}", "/p:Platform=x64", "/nologo", "/v:minimal"]
    props = ["/p:GenerateAppxPackageOnBuild=true", "/p:AppxBundle=Never", f"/p:AppxPackageDir={package_dir}\\",
             f"/p:StageDir={STAGE_DIR}\\", f"/p:Version={version}"]
    if store:
        # No symbol package (.appxsym) in the upload: its PDB check task fails with MSB6011 on this project (seen
        # 2026-10-12 with the MSIX tools 1.7.251221100), and symbols are optional for the Store; the source is public.
        props += ["/p:UapAppxPackageBuildMode=StoreUpload", "/p:AppxPackageSigningEnabled=false",
                  "/p:AppxSymbolPackageEnabled=false"]
    else:
        if pfx is None:
            raise ValueError("a sideload build needs --sideload CERT.pfx")
        props += ["/p:UapAppxPackageBuildMode=SideloadOnly", "/p:AppxPackageSigningEnabled=true",
                  f"/p:PackageCertificateKeyFile={pfx.resolve()}"]
        if password:
            props.append(f"/p:PackageCertificatePassword={password}")
    with LOG.open("w", encoding="utf-8") as log:
        for step, args in (("restore", [str(msbuild_exe), str(PROJECT), "/t:Restore", *common, f"/p:StageDir={STAGE_DIR}\\"]),
                           ("build", [str(msbuild_exe), str(PROJECT), *common, *props])):
            shown = [a for a in args if not a.startswith("/p:PackageCertificatePassword")]
            log.write(f"== {step}: {' '.join(shown)}\n")
            log.flush()
            done = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, text=True, check=False)
            if done.returncode != 0:
                raise RuntimeError(f"msbuild {step} failed with {done.returncode}; see {LOG}")
    suffix = ".msixupload" if store else ".msix"
    # MSBuild puts the framework packages the app depends on (the Windows App Runtime, VCLibs) in a Dependencies
    # folder beside the app's package: only the app's own package is ours.
    found = sorted(p for p in package_dir.rglob(f"*{suffix}") if "Dependencies" not in p.parts)
    if len(found) != 1:
        raise RuntimeError(f"expected one {suffix} under {package_dir}, found {len(found)}: {[p.name for p in found]}; see {LOG}")
    return found


def deliver(files: list[Path], out_dir: Path, version: str) -> list[Path]:
    """Copy the packages into ``out_dir`` under the release names, each with its ``.sha256`` file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    delivered = []
    for src in files:
        dest = out_dir / f"ai-session-usage-{version}-x64{src.suffix}"
        shutil.copyfile(src, dest)
        (out_dir / f"{dest.name}.sha256").write_text(f"{sha256_of(dest)}  {dest.name}\n", encoding="ascii")
        delivered.append(dest)
    return delivered


def main() -> None:
    """Read the command line, stage the package's contents, and on Windows build and deliver it."""
    parser = argparse.ArgumentParser(description="Stage and build the Widgets Board package.")
    parser.add_argument("--stage-only", action="store_true", help="stage the helper and Python, build nothing")
    parser.add_argument("--store", action="store_true", help="an unsigned .msixupload for Partner Center")
    parser.add_argument("--sideload", type=Path, metavar="CERT.pfx", help="a .msix signed with this certificate")
    parser.add_argument("--password", help="the certificate's password, when it has one")
    parser.add_argument("--out", type=Path, default=ROOT / "dist", help="where the packages go (default dist/)")
    parser.add_argument("--configuration", default="Release")
    parser.add_argument("--msbuild", help="MSBuild.exe, when vswhere should not choose")
    parser.add_argument("--python-zip", type=Path, help="the embeddable package, already downloaded")
    args = parser.parse_args()
    if not args.stage_only and not args.store and args.sideload is None:
        parser.error("one of --stage-only, --store, --sideload CERT.pfx")
    version = check_versions()
    python_zip = args.python_zip if args.python_zip else ensure_python_zip()
    summary = stage(STAGE_DIR, python_zip, PYTHON_SHA256)
    print(f"staged: {STAGE_DIR.relative_to(ROOT)} (python {PYTHON_VERSION}, {len(summary['helper'])} helper files, version {version})")
    if args.stage_only:
        return
    if sys.platform != "win32":
        raise SystemExit("building the package needs MSBuild on Windows; here only --stage-only works")
    exe = find_msbuild(args.msbuild)
    files = msbuild(exe, version, args.configuration, args.store, args.sideload, args.password)
    for dest in deliver(files, args.out, version):
        print(f"built: {dest} ({dest.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
