import struct
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.apk_equivalence import EquivalenceError, compare_apks


COMMON_ENTRIES = [
    ("AndroidManifest.xml", b"manifest"),
    ("assets/payload.bin", b"payload bytes"),
]
SIGNATURE_ENTRIES = [
    ("META-INF/MANIFEST.MF", b"manifest digest"),
    ("META-INF/TVBOXOSC.SF", b"signature file"),
    ("META-INF/TVBOXOSC.RSA", b"certificate"),
]


def write_apk(path, entries):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data, *metadata in entries:
            info = zipfile.ZipInfo(name, date_time=(2024, 1, 2, 3, 4, 6))
            if metadata and metadata[0] == "symlink":
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)


def signed_entries(extra=()):
    return [*COMMON_ENTRIES, *SIGNATURE_ENTRIES, *extra]


class ApkEquivalenceTests(unittest.TestCase):
    def test_identical_payload_with_only_signature_entries_is_equivalent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsigned = root / "unsigned.apk"
            signed = root / "signed.apk"
            write_apk(unsigned, COMMON_ENTRIES)
            write_apk(signed, signed_entries())

            result = compare_apks(signed, unsigned)

            self.assertEqual(result["schema"], "tvbox-apk-equivalence-v1")
            self.assertEqual(result["status"], "equivalent")
            self.assertEqual(result["common_entry_count"], len(COMMON_ENTRIES))
            self.assertEqual(result["signature_entries"], [name for name, _ in SIGNATURE_ENTRIES])

    def test_one_byte_payload_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsigned = root / "unsigned.apk"
            signed = root / "signed.apk"
            write_apk(unsigned, COMMON_ENTRIES)
            write_apk(signed, signed_entries())
            raw = bytearray(signed.read_bytes())
            local = raw.find(b"PK\x03\x04")
            name_length, extra_length = struct.unpack_from("<HH", raw, local + 26)
            raw[local + 30 + name_length + extra_length] ^= 1
            signed.write_bytes(raw)

            with self.assertRaisesRegex(EquivalenceError, "local record differs"):
                compare_apks(signed, unsigned)

    def test_zip_metadata_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsigned = root / "unsigned.apk"
            signed = root / "signed.apk"
            write_apk(unsigned, COMMON_ENTRIES)
            write_apk(signed, signed_entries())
            raw = bytearray(signed.read_bytes())
            central = raw.find(b"PK\x01\x02")
            struct.pack_into("<H", raw, central + 8, 0x800)
            signed.write_bytes(raw)

            with self.assertRaisesRegex(EquivalenceError, "central directory record differs"):
                compare_apks(signed, unsigned)

    def test_extra_nested_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsigned = root / "unsigned.apk"
            signed = root / "signed.apk"
            write_apk(unsigned, COMMON_ENTRIES)
            write_apk(signed, signed_entries((("assets/nested/extra.bin", b"pollution"),)))

            with self.assertRaisesRegex(EquivalenceError, "unexpected signed-only entries"):
                compare_apks(signed, unsigned)

    def test_symlink_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsigned = root / "unsigned.apk"
            signed = root / "signed.apk"
            write_apk(unsigned, COMMON_ENTRIES)
            write_apk(signed, signed_entries((("META-INF/evil-link", b"target", "symlink"),)))

            with self.assertRaisesRegex(EquivalenceError, "symlink"):
                compare_apks(signed, unsigned)


if __name__ == "__main__":
    unittest.main(verbosity=2)
