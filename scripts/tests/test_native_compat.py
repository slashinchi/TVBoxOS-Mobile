import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.native_compat import (
    KNOWN_INCOMPATIBLE_PATHS,
    canonical_report,
    inspect_apk,
    parse_readelf_program_headers,
    summarize_report,
)


class NativeCompatibilityTests(unittest.TestCase):
    def test_4k_load_is_incompatible(self):
        component = parse_readelf_program_headers(
            """
            Program Headers:
              LOAD           0x000000 0x000000 0x000000 0x1000 0x1000 R E 0x1000
              GNU_RELRO      0x000000 0x000000 0x000000 0x1000 0x1000 R   0x1
            """,
            "lib/arm64-v8a/libquickjs-android-wrapper.so",
        )
        self.assertEqual(component["min_load_align"], 0x1000)
        self.assertFalse(component["compatible"])
        self.assertTrue(component["relro"])

    def test_16k_and_64k_loads_are_compatible(self):
        for alignment in ("0x4000", "0x10000"):
            component = parse_readelf_program_headers(
                f"LOAD 0x0 0x0 0x0 0x1000 0x1000 R E {alignment}\n",
                "lib/arm64-v8a/libavcodec.so",
            )
            self.assertTrue(component["compatible"])

    def test_known_debt_is_explicit_and_unexpected_debt_fails(self):
        components = [
            {
                "path": path,
                "min_load_align": 0x1000,
                "relro": True,
                "compatible": False,
            }
            for path in sorted(KNOWN_INCOMPATIBLE_PATHS)
        ]
        summary = summarize_report(components)
        self.assertEqual(summary["status"], "known-debt")
        self.assertEqual(summary["incompatible_count"], 3)
        with self.assertRaisesRegex(ValueError, "unexpected native compatibility debt"):
            summarize_report(components + [{**components[0], "path": "lib/arm64-v8a/new.so"}])

    def test_report_schema_is_stable(self):
        report = canonical_report(
            [{"path": "lib/arm64-v8a/libavcodec.so", "min_load_align": 0x10000, "relro": True, "compatible": True}]
        )
        self.assertEqual(report["schema"], "tvbox-native-compat-v1")
        self.assertEqual(report["min_required_load_align"], 0x4000)

    def test_inspects_every_64_bit_library_and_preserves_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apk = root / "fixture.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                for path in (
                    "lib/arm64-v8a/libavcodec.so",
                    "lib/arm64-v8a/libquickjs-android-wrapper.so",
                    "lib/x86_64/libfixture.so",
                ):
                    archive.writestr(path, b"synthetic ELF")
            reader = root / "llvm-readelf"
            reader.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "alignment = '0x1000' if sys.argv[-1].endswith('native-1.so') else '0x10000'\n"
                "print(f'LOAD 0x0 0x0 0x0 0x1000 0x1000 R E {alignment}')\n"
                "print('GNU_RELRO 0x0 0x0 0x0 0x0 0x0 R 0x1')\n"
            )
            reader.chmod(reader.stat().st_mode | 0o111)

            components = inspect_apk(apk, reader)

            self.assertEqual([item["path"] for item in components], [
                "lib/arm64-v8a/libavcodec.so",
                "lib/arm64-v8a/libquickjs-android-wrapper.so",
                "lib/x86_64/libfixture.so",
            ])
            self.assertEqual(components[0]["min_load_align"], 0x10000)
            self.assertFalse(components[1]["compatible"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
