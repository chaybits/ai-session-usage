#!/usr/bin/env python3
"""The Widgets Board package's staging and its version carriers, on any platform (the MSIX itself needs Windows).

Checks scripts/build_msix.py's staging on a zip made here (the shape of python.org's embeddable package: python.exe,
the stdlib zip, a ._pth), the checksum refusal, that the helper staged is byte for byte the Source helper with the
metadata beside it, and the things that must agree across files: the manifest's version against src/metadata.json,
the COM class id across the manifest and WidgetProvider.cs, every picture the manifest names, the card template's
bindings against the keys Card.cs writes, and the CI pins. Run: python3 -B tests/test_msix_stage.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_msix  # noqa: E402

try:
    from PIL import Image
except ImportError:  # the picture check needs Pillow; everything else here is the standard library
    Image = None

PROJECT_DIR = ROOT / "widgets-board" / "AiSessionUsage"
MANIFEST = PROJECT_DIR / "Package.appxmanifest"
TEMPLATE = PROJECT_DIR / "Templates" / "card.json"
PROVIDER_CS = PROJECT_DIR / "WidgetProvider.cs"
CARD_CS = ROOT / "widgets-board" / "AiSessionUsage.Core" / "Card.cs"


def fake_embeddable_zip(path: Path, with_pth: bool = True) -> str:
    """A zip shaped like python.org's embeddable package; returns its SHA-256."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("python.exe", b"MZ fake")
        zf.writestr("python313.dll", b"fake dll")
        zf.writestr("python313.zip", b"PK fake stdlib")
        if with_pth:
            zf.writestr("python313._pth", "python313.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n")
        zf.writestr("LICENSE.txt", "PSF")
        zf.writestr("../escape.txt", "must not be extracted")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.zip = self.dir / "python-3.13.16-embed-amd64.zip"
        self.sha = fake_embeddable_zip(self.zip)
        self.stage = self.dir / "stage"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_stage_lays_out_python_and_the_helper(self) -> None:
        summary = build_msix.stage(self.stage, self.zip, self.sha)
        self.assertTrue((self.stage / "python" / "python.exe").is_file())
        self.assertTrue((self.stage / "python" / "python313.zip").is_file())
        self.assertFalse((self.stage / "escape.txt").exists())
        self.assertFalse((self.dir / "escape.txt").exists())
        pth = (self.stage / "python" / "python313._pth").read_bytes()
        self.assertEqual(b"python313.zip\r\n.\r\n..\\code\r\n", pth)
        for name in ("fetch_usage.py", "usage_common.py", "usage_claude.py", "usage_codex.py", "usage_statusline.py",
                     "usage_claudecode.py", "statusline_tap.py"):
            staged = self.stage / "code" / name
            self.assertTrue(staged.is_file(), name)
            self.assertEqual((ROOT / "src" / "contents" / "code" / name).read_bytes(), staged.read_bytes(), name)
        self.assertEqual((ROOT / "src" / "metadata.json").read_bytes(), (self.stage / "code" / "metadata.json").read_bytes())
        self.assertFalse(list((self.stage / "code").glob("__pycache__")))
        self.assertEqual(build_msix.package_version(), summary["version"])
        self.assertEqual(json.loads((self.stage / "STAGE.json").read_text(encoding="utf-8"))["pth"], "python313._pth")

    def test_stage_is_rebuilt_from_scratch(self) -> None:
        build_msix.stage(self.stage, self.zip, self.sha)
        leftover = self.stage / "code" / "old.pyc"
        leftover.write_bytes(b"x")
        build_msix.stage(self.stage, self.zip, self.sha)
        self.assertFalse(leftover.exists())

    def test_wrong_checksum_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            build_msix.stage(self.stage, self.zip, "0" * 64)
        self.assertFalse(self.stage.exists())

    def test_a_zip_without_pth_is_refused(self) -> None:
        other = self.dir / "other.zip"
        sha = fake_embeddable_zip(other, with_pth=False)
        with self.assertRaises(ValueError):
            build_msix.stage(self.stage, other, sha)

    def test_ensure_python_zip_refuses_a_bad_download(self) -> None:
        downloads = self.dir / "downloads"
        downloads.mkdir()
        bad = downloads / build_msix.PYTHON_ZIP_NAME
        bad.write_bytes(b"not the zip")
        with self.assertRaises(ValueError):
            build_msix.ensure_python_zip(downloads)
        self.assertFalse(bad.exists())


class CarrierTests(unittest.TestCase):
    def test_manifest_version_is_the_program_version_with_a_zero(self) -> None:
        self.assertEqual(f"{build_msix.package_version()}.0", build_msix.manifest_version())
        self.assertEqual(build_msix.package_version(), build_msix.check_versions())

    def test_check_versions_refuses_a_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "Package.appxmanifest"
            bad.write_text(MANIFEST.read_text(encoding="utf-8").replace(f'Version="{build_msix.package_version()}.0"', 'Version="9.9.9.0"'), encoding="utf-8")
            self.assertEqual("9.9.9.0", build_msix.manifest_version(bad))
            original = build_msix.MANIFEST
            build_msix.MANIFEST = bad
            try:
                with self.assertRaises(ValueError):
                    build_msix.check_versions()
            finally:
                build_msix.MANIFEST = original

    def test_class_id_agrees_across_manifest_and_code(self) -> None:
        manifest = MANIFEST.read_text(encoding="utf-8")
        ids = set(re.findall(r'<com:Class Id="([0-9A-Fa-f-]{36})"', manifest))
        ids |= set(re.findall(r'<CreateInstance ClassId="([0-9A-Fa-f-]{36})"', manifest))
        code = re.search(r'ClassId = "([0-9A-Fa-f-]{36})"', PROVIDER_CS.read_text(encoding="utf-8"))
        self.assertIsNotNone(code)
        self.assertEqual({code.group(1)}, ids)
        definition = re.search(r'<Definition Id="([^"]+)"', manifest).group(1)
        self.assertIn(f'DefinitionId = "{definition}"', PROVIDER_CS.read_text(encoding="utf-8"))

    def test_manifest_names_existing_pictures_and_the_right_capabilities(self) -> None:
        manifest = MANIFEST.read_text(encoding="utf-8")
        pictures = set(re.findall(r'(?:Logo|Image|Path)="([^"]+\.png)"', manifest))
        self.assertGreaterEqual(len(pictures), 6)
        for p in pictures:
            self.assertTrue((PROJECT_DIR / p.replace("\\", "/")).is_file(), p)
        self.assertIn('<rescap:Capability Name="runFullTrust" />', manifest)
        self.assertNotIn("internetClient", manifest)
        self.assertIn('MinVersion="10.0.22621.0"', manifest)
        self.assertIn('Executable="AiSessionUsage.exe" Arguments="-RegisterProcessAsComServer"', manifest)
        self.assertIn('<uap3:AppExtension Name="com.microsoft.windows.widgets"', manifest)
        for size in ("small", "medium", "large"):
            self.assertIn(f'<Size Name="{size}" />', manifest)

    @unittest.skipIf(Image is None, "Pillow is not installed (pip install pillow)")
    def test_picker_previews_are_the_picker_size(self) -> None:
        for name in ("WidgetScreenshot.png", "WidgetScreenshotDark.png"):
            with Image.open(PROJECT_DIR / "ProviderAssets" / name) as img:
                self.assertEqual((300, 304), img.size, name)
                self.assertEqual("RGBA", img.mode, name)
                self.assertEqual(0, img.getpixel((0, 0))[3], f"{name}: the corners are transparent")
                self.assertEqual(255, img.getpixel((150, 152))[3], f"{name}: the middle is opaque")

    def test_template_and_card_data_agree(self) -> None:
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual("1.5", template["version"])
        # The refresh is a click anywhere on the card (the card's one container), the way the Plasma widget and the
        # skin refresh; there is no button, whose row the medium widget has no room for.
        self.assertNotIn("actions", template)
        action = template["body"][0]["selectAction"]
        verb = re.search(r'RefreshVerb = "(\w+)"', PROVIDER_CS.read_text(encoding="utf-8")).group(1)
        self.assertEqual(("Action.Execute", verb), (action["type"], action["verb"]))
        # The card's fields are JsonObject entries whose value is an expression; the lookup tables in Card.cs (the bar
        # colours, the messages) are dictionary entries whose value is a plain string literal, and are not fields.
        written = set(re.findall(r'\["(\w+)"\] = (?!")', CARD_CS.read_text(encoding="utf-8")))
        bound = set(re.findall(r"\$\{\$?([A-Za-z_]\w*)", TEMPLATE.read_text(encoding="utf-8")))
        bound -= {"root", "host", "data", "index"}
        self.assertEqual([], sorted(bound - written), "bound in the template, never written by Card.cs")
        self.assertEqual([], sorted(written - bound), "written by Card.cs, bound nowhere in the template")

    def test_workflows_pin_actions_by_sha(self) -> None:
        for name in ("ci.yml", "release.yml"):
            text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            for use in re.findall(r"uses:\s*(\S+)", text):
                self.assertRegex(use, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$", f"{name}: {use}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
