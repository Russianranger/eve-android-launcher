"""Exercise the publication guard against real divergent Git histories."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("release_lineage", Path(__file__).resolve().parents[1] / "scripts/check-release-lineage.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReleaseLineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        (self.root / "app").mkdir()
        (self.root / ".github/workflows").mkdir(parents=True)
        self.write_version(23, "0.1.22")
        self.git("add", ".")
        self.git("commit", "-qm", "Delivered development")
        self.baseline = self.git("rev-parse", "HEAD")

    def git(self, *arguments):
        return subprocess.check_output(["git", "-C", str(self.root), *arguments], text=True).strip()

    def write_version(self, code, name):
        (self.root / "app/build.gradle").write_text(f"versionCode {code}\nversionName '{name}'\n")
        (self.root / ".github/workflows/build.yml").write_text(f"env:\n  EVE_APP_VERSION: '{name}'\n")

    def test_descendant_with_newer_identity_passes(self):
        self.write_version(24, "0.1.23")
        MODULE.check(self.root, self.baseline)

    def test_old_or_inconsistent_version_cannot_publish(self):
        for code, name in ((9, "0.1.8"), (23, "0.1.23"), (24, "0.1.22")):
            with self.subTest(code=code, name=name), self.assertRaisesRegex(ValueError, "newer"):
                self.write_version(code, name)
                MODULE.check(self.root, self.baseline)
        self.write_version(24, "0.1.23")
        (self.root / ".github/workflows/build.yml").write_text("EVE_APP_VERSION: '0.1.8'")
        with self.assertRaisesRegex(ValueError, "versions differ"):
            MODULE.check(self.root, self.baseline)

    def test_unrelated_branch_rejected_even_with_higher_version(self):
        self.git("checkout", "--orphan", "old-main")
        self.git("rm", "-rfq", ".")
        (self.root / "app").mkdir()
        (self.root / ".github/workflows").mkdir(parents=True)
        self.write_version(25, "0.1.24")
        self.git("add", ".")
        self.git("commit", "-qm", "Wrong baseline")
        with self.assertRaisesRegex(ValueError, "does not include"):
            MODULE.check(self.root, self.baseline)
