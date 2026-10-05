"""Verify compiled release flags without treating activity attributes as app flags."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "check_apk", Path(__file__).resolve().parents[1] / "scripts" / "check-apk.py")
check_apk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_apk)

TREE = """N: android=http://schemas.android.com/apk/res/android
  E: manifest (line=1)
    E: application (line=8)
      A: android:debuggable(0x0101000f)=(type 0x12)0x0
      E: profileable (line=9)
        A: android:shell(0x0101061b)=(type 0x12)0xffffffff
        A: android:enabled(0x0101000e)=(type 0x12)0xffffffff
      E: activity (line=10)
        A: android:enabled(0x0101000e)=(type 0x12)0x0
"""


class CompiledManifestTests(unittest.TestCase):
    def test_non_debuggable_profileable_release(self):
        check_apk.check_manifest(TREE)
        # Omitted debuggable/enabled values use the Android defaults.
        check_apk.check_manifest(TREE.replace(
            "      A: android:debuggable(0x0101000f)=(type 0x12)0x0\n", "").replace(
            "        A: android:enabled(0x0101000e)=(type 0x12)0xffffffff\n", ""))

    def test_debuggable_apk_rejected(self):
        with self.assertRaisesRegex(ValueError, "must not be debuggable"):
            check_apk.check_manifest(TREE.replace(
                "android:debuggable(0x0101000f)=(type 0x12)0x0",
                "android:debuggable(0x0101000f)=(type 0x12)0xffffffff"))

    def test_profileable_must_be_enabled_for_shell(self):
        for source in (
            TREE.replace("android:shell(0x0101061b)=(type 0x12)0xffffffff",
                         "android:shell(0x0101061b)=(type 0x12)0x0"),
            TREE.replace("android:enabled(0x0101000e)=(type 0x12)0xffffffff",
                         "android:enabled(0x0101000e)=(type 0x12)0x0"),
            TREE.replace("      E: profileable", "        E: profileable"),
            TREE.replace("E: profileable", "E: service"),
        ):
            with self.subTest(tree=source), self.assertRaises(ValueError):
                check_apk.check_manifest(source)

    def test_unrecognized_flag_cannot_silently_pass(self):
        with self.assertRaisesRegex(ValueError, "Unrecognized compiled"):
            check_apk.check_manifest(TREE.replace(
                "android:debuggable(0x0101000f)=(type 0x12)0x0",
                'android:debuggable(0x0101000f)="true"'))

    def test_no_manifest_cannot_silently_pass(self):
        with self.assertRaises(ValueError):
            check_apk.check_manifest("")


if __name__ == "__main__":
    unittest.main()
