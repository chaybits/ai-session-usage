"""Tests for scripts/build_rmskin.py: the zip's contents, Rainmeter's footer, the installer manifest, the checksum,
byte-identical builds. The skin's own logic is tests/test_skin_lua.py; its look needs Rainmeter (the Windows VM)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD = ROOT / "scripts" / "build_rmskin.py"
SKIN = ROOT / "rainmeter" / "AiSessionUsage"
CODE = ROOT / "src/contents/code"


def build_ok(out: Path) -> tuple[Path, Path]:
    proc = subprocess.run([sys.executable, "-B", str(BUILD), "--out", str(out)], capture_output=True, text=True,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    if proc.returncode != 0:
        raise AssertionError(f"build failed: {proc.stderr}")
    rmskin, checksum = (Path(line) for line in proc.stdout.splitlines())
    return rmskin, checksum


class TestRmskin(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cu-rmskin-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.rmskin, self.checksum = build_ok(self.tmp / "dist")
        self.data = self.rmskin.read_bytes()

    def test_named_after_the_version_and_footed_for_the_installer(self) -> None:
        version = json.loads((ROOT / "src/metadata.json").read_text(encoding="utf-8"))["KPlugin"]["Version"]
        self.assertEqual(self.rmskin.name, f"ai-session-usage-{version}.rmskin")
        size, flags, key = struct.unpack("<qB7s", self.data[-16:])
        self.assertEqual((size, flags, key), (len(self.data) - 16, 0, b"RMSKIN\0"),
                         "the footer Rainmeter's installer checks: the zip's length, no flags, the key")

    def test_the_zip_holds_the_manifest_the_skin_and_the_helper(self) -> None:
        with zipfile.ZipFile(self.rmskin) as archive:  # zipfile finds the directory before the footer
            names = sorted(archive.namelist())
            self.assertIn("RMSKIN.ini", names)
            ini = archive.read("RMSKIN.ini").decode("utf-8")
            self.assertIn("[rmskin]\r\nName=ai-session-usage\r\n", ini)
            self.assertIn("Load=AiSessionUsage\\AiSessionUsage.ini", ini)
            self.assertIn("Skins/AiSessionUsage/AiSessionUsage.ini", names)
            self.assertIn("Skins/AiSessionUsage/@Resources/Scripts/AiSessionUsage.lua", names)
            helpers = sorted(n for n in names if n.startswith("Skins/AiSessionUsage/@Resources/code/"))
            self.assertEqual(helpers, sorted(f"Skins/AiSessionUsage/@Resources/code/{p.name}" for p in CODE.glob("*.py")))
            for name in helpers:
                self.assertEqual(archive.read(name), (CODE / Path(name).name).read_bytes(), name)
            self.assertFalse(any(".pyc" in n or "__pycache__" in n for n in names))
            for name in names:
                self.assertEqual(archive.getinfo(name).compress_type, zipfile.ZIP_STORED)

    def test_the_skin_ini_has_the_metadata_with_the_project_link(self) -> None:
        raw = (SKIN / "AiSessionUsage.ini").read_bytes()
        self.assertIn(b"\r\n", raw, "CRLF, as Rainmeter writes its files")
        ini = raw.decode("utf-8")
        self.assertIn("[Metadata]", ini)
        self.assertIn("https://github.com/chaybits/ai-session-usage", ini)
        self.assertIn("License=GPL-3.0-or-later", ini)
        version = json.loads((ROOT / "src/metadata.json").read_text(encoding="utf-8"))["KPlugin"]["Version"]
        self.assertIn(f"Version={version}", ini, "the skin's metadata carries the package version")
        self.assertNotIn("\N{EM DASH}", ini)
        self.assertNotIn("\N{EM DASH}", (SKIN / "@Resources/Scripts/AiSessionUsage.lua").read_text(encoding="utf-8"))

    def test_checksum_matches_and_two_builds_are_byte_identical(self) -> None:
        digest, name = self.checksum.read_text(encoding="utf-8").split()
        self.assertEqual((name, digest), (self.rmskin.name, hashlib.sha256(self.data).hexdigest()))
        again, _ = build_ok(self.tmp / "again")
        self.assertEqual(again.read_bytes(), self.data)


if __name__ == "__main__":
    unittest.main(verbosity=1)
