"""Tests for scripts/build_plasmoid.py and the package it makes.

The zip holds exactly the package's files with metadata.json at the root, its checksum file matches, two builds
are byte-identical, a compiled module in the tree is refused; and, where kpackagetool6 exists, the package
installs into a clean data folder and Plasma can read it back. Nothing touches the real ~/.local/share.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"
BUILD = ROOT / "scripts" / "build_plasmoid.py"
PLUGIN_ID = "io.github.chaybits.aisessionusage"
KPACKAGETOOL = shutil.which("kpackagetool6")


def package_paths(folder: Path) -> list[str]:
    """Every file under ``folder`` as a package-relative POSIX path, compiled Python left out, sorted."""
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")


def run_build(out: Path, src: Path = SRC) -> subprocess.CompletedProcess:
    """Run the build script as a subprocess, the way the workflow does."""
    return subprocess.run([sys.executable, "-B", str(BUILD), "--src", str(src), "--out", str(out)],
                          capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))


def build_ok(out: Path) -> tuple[Path, Path]:
    """Build and return ``(plasmoid, checksum)``, asserting the script succeeded."""
    proc = run_build(out)
    if proc.returncode != 0:
        raise AssertionError(f"build failed: {proc.stderr}")
    plasmoid, checksum = (Path(line) for line in proc.stdout.splitlines())
    return plasmoid, checksum


class TestBuild(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cu-package-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.plasmoid, self.checksum = build_ok(self.tmp / "dist")

    def test_named_after_the_version_in_metadata(self) -> None:
        version = json.loads((SRC / "metadata.json").read_text(encoding="utf-8"))["KPlugin"]["Version"]
        self.assertEqual(self.plasmoid.name, f"ai-session-usage-{version}.plasmoid")
        self.assertEqual(self.checksum.name, f"{self.plasmoid.name}.sha256")

    def test_holds_exactly_the_package_files_with_metadata_at_the_root(self) -> None:
        with zipfile.ZipFile(self.plasmoid) as archive:
            names = sorted(archive.namelist())
            self.assertEqual(names, package_paths(SRC))
            self.assertIn("metadata.json", names, "Plasma reads the id and version from the root")
            for name in names:
                self.assertEqual(archive.read(name), (SRC / name).read_bytes(), name)
                self.assertEqual(archive.getinfo(name).date_time, (1980, 1, 1, 0, 0, 0), "one fixed timestamp")

    def test_checksum_file_matches_and_is_in_sha256sum_form(self) -> None:
        digest, name = self.checksum.read_text(encoding="utf-8").split()
        self.assertEqual(name, self.plasmoid.name)
        self.assertEqual(digest, hashlib.sha256(self.plasmoid.read_bytes()).hexdigest())
        if shutil.which("sha256sum"):
            done = subprocess.run(["sha256sum", "-c", self.checksum.name], cwd=self.checksum.parent,
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_two_builds_are_byte_identical(self) -> None:
        again, _ = build_ok(self.tmp / "again")
        self.assertEqual(again.read_bytes(), self.plasmoid.read_bytes())

    def test_a_compiled_module_in_the_tree_is_refused(self) -> None:
        copy = self.tmp / "src"
        shutil.copytree(SRC, copy, ignore=shutil.ignore_patterns("__pycache__"))
        cache = copy / "contents/code/__pycache__"
        cache.mkdir()
        (cache / "usage_common.cpython-312.pyc").write_bytes(b"\x00")
        proc = run_build(self.tmp / "refused", src=copy)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("__pycache__", proc.stderr)
        self.assertEqual(list((self.tmp / "refused").glob("*")) if (self.tmp / "refused").exists() else [], [],
                         "nothing is written on a refusal")


@unittest.skipUnless(KPACKAGETOOL, "SKIPPED: kpackagetool6 not found, the install was not tried")
class TestInstall(unittest.TestCase):
    def test_installs_into_a_clean_data_folder_and_plasma_reads_it(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cu-install-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        plasmoid, _ = build_ok(tmp / "dist")
        (tmp / "home").mkdir()
        env = dict(os.environ, HOME=str(tmp / "home"), XDG_DATA_HOME=str(tmp / "data"), XDG_CACHE_HOME=str(tmp / "cache"))
        install = subprocess.run([KPACKAGETOOL, "--type", "Plasma/Applet", "--install", str(plasmoid)],
                                 env=env, capture_output=True, text=True)
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        installed = tmp / "data/plasma/plasmoids" / PLUGIN_ID
        self.assertEqual(package_paths(installed), package_paths(SRC), "every file of the package, nothing else")
        show = subprocess.run([KPACKAGETOOL, "--type", "Plasma/Applet", "--show", PLUGIN_ID],
                              env=env, capture_output=True, text=True)
        self.assertEqual(show.returncode, 0, show.stdout + show.stderr)
        self.assertIn("AI Session Usage", show.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)
