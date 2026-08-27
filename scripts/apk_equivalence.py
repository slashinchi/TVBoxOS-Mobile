#!/usr/bin/env python3
"""Verify APK payload equivalence without reconstructing or rewriting signatures."""

import argparse
import base64
import hashlib
import json
import stat
import struct
import sys
from pathlib import Path


EOCD = b"PK\x05\x06"
CENTRAL = b"PK\x01\x02"
LOCAL = b"PK\x03\x04"
SIGNATURE_SUFFIXES = (b".SF", b".RSA", b".DSA", b".EC")


class EquivalenceError(ValueError):
    """Raised when a signed APK does not preserve the unsigned APK payload."""


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _display_name(name):
    return name.decode("utf-8", "backslashreplace")


def _is_signature_entry(name):
    return name == b"META-INF/MANIFEST.MF" or (
        name.startswith(b"META-INF/") and name.endswith(SIGNATURE_SUFFIXES)
    )


def _is_symlink(create_system, external_attr):
    if create_system != 3:
        return False
    return stat.S_ISLNK((external_attr >> 16) & 0xFFFF)


def _parse_archive(path):
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EquivalenceError(f"cannot read APK {path}: {exc}") from exc

    eocd = raw.rfind(EOCD)
    if eocd < 0 or eocd + 22 > len(raw):
        raise EquivalenceError(f"EOCD not found: {path}")
    comment_length = struct.unpack_from("<H", raw, eocd + 20)[0]
    if eocd + 22 + comment_length > len(raw):
        raise EquivalenceError(f"truncated EOCD: {path}")
    entry_count = struct.unpack_from("<H", raw, eocd + 10)[0]
    cd_size = struct.unpack_from("<I", raw, eocd + 12)[0]
    cd_offset = struct.unpack_from("<I", raw, eocd + 16)[0]
    if entry_count == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
        raise EquivalenceError(f"ZIP64 APKs are unsupported: {path}")
    if cd_offset + cd_size > len(raw):
        raise EquivalenceError(f"truncated central directory: {path}")

    central = raw[cd_offset:cd_offset + cd_size]
    records = []
    names = set()
    offset = 0
    while offset < len(central):
        if central[offset:offset + 4] != CENTRAL or offset + 46 > len(central):
            raise EquivalenceError(f"invalid central directory record at {offset}: {path}")
        version_made = struct.unpack_from("<H", central, offset + 4)[0]
        flag_bits = struct.unpack_from("<H", central, offset + 8)[0]
        compressed_size = struct.unpack_from("<I", central, offset + 20)[0]
        file_size = struct.unpack_from("<I", central, offset + 24)[0]
        name_length, extra_length, comment_length = struct.unpack_from(
            "<HHH", central, offset + 28
        )
        record_length = 46 + name_length + extra_length + comment_length
        if offset + record_length > len(central):
            raise EquivalenceError(f"truncated central directory record: {path}")
        name_start = offset + 46
        name = central[name_start:name_start + name_length]
        if name in names:
            raise EquivalenceError(f"duplicate ZIP entry: {_display_name(name)}")
        names.add(name)
        external_attr = struct.unpack_from("<I", central, offset + 38)[0]
        local_offset = struct.unpack_from("<I", central, offset + 42)[0]
        if _is_symlink(version_made >> 8, external_attr):
            raise EquivalenceError(f"symlink ZIP entry: {_display_name(name)}")
        if local_offset + 30 > len(raw) or raw[local_offset:local_offset + 4] != LOCAL:
            raise EquivalenceError(f"invalid local record: {_display_name(name)}")
        local_name_length, local_extra_length = struct.unpack_from(
            "<HH", raw, local_offset + 26
        )
        local_name_start = local_offset + 30
        local_name = raw[local_name_start:local_name_start + local_name_length]
        if local_name != name:
            raise EquivalenceError(f"local/central name mismatch: {_display_name(name)}")
        data_start = local_name_start + local_name_length + local_extra_length
        data_end = data_start + compressed_size
        if data_end > len(raw):
            raise EquivalenceError(f"truncated local record: {_display_name(name)}")
        records.append(
            {
                "name": name,
                "central_record": central[offset:offset + record_length],
                "local_record": raw[local_offset:data_end],
                "local_offset": local_offset,
                "data_end": data_end,
                "flag_bits": flag_bits,
                "compressed_size": compressed_size,
                "file_size": file_size,
            }
        )
        offset += record_length
    if offset != len(central):
        raise EquivalenceError(f"central directory length mismatch: {path}")

    previous_end = 0
    for record in sorted(records, key=lambda item: item["local_offset"]):
        if record["local_offset"] < previous_end:
            raise EquivalenceError(f"overlapping local records: {path}")
        record["prefix_padding"] = raw[previous_end:record["local_offset"]]
        previous_end = record["data_end"]

    return {
        "path": str(path),
        "raw": raw,
        "sha256": _sha256(raw),
        "size": len(raw),
        "central_directory_offset": cd_offset,
        "central_directory_size": cd_size,
        "records": records,
        "by_name": {record["name"]: record for record in records},
    }


def compare_apks(signed, unsigned):
    signed_archive = _parse_archive(signed)
    unsigned_archive = _parse_archive(unsigned)
    signed_records = signed_archive["records"]
    unsigned_records = unsigned_archive["records"]
    unsigned_names = [record["name"] for record in unsigned_records]
    signed_names = [record["name"] for record in signed_records]

    unsigned_signature_entries = [name for name in unsigned_names if _is_signature_entry(name)]
    if unsigned_signature_entries:
        raise EquivalenceError("unsigned APK already contains signature entries")

    signed_only = [name for name in signed_names if name not in unsigned_archive["by_name"]]
    unexpected = [name for name in signed_only if not _is_signature_entry(name)]
    if unexpected:
        names = ", ".join(_display_name(name) for name in unexpected)
        raise EquivalenceError(f"unexpected signed-only entries: {names}")

    first_signature_index = next(
        (index for index, name in enumerate(signed_names) if _is_signature_entry(name)),
        len(signed_names),
    )
    if any(not _is_signature_entry(name) for name in signed_names[first_signature_index:]):
        raise EquivalenceError("signature entries must be a central-directory suffix")
    common_signed_names = signed_names[:first_signature_index]
    if common_signed_names != unsigned_names:
        raise EquivalenceError("common ZIP entry order differs")

    for unsigned_record in unsigned_records:
        name = unsigned_record["name"]
        signed_record = signed_archive["by_name"].get(name)
        if signed_record is None:
            raise EquivalenceError(f"missing signed entry: {_display_name(name)}")
        if signed_record["central_record"] != unsigned_record["central_record"]:
            raise EquivalenceError(
                f"central directory record differs: {_display_name(name)}"
            )
        if signed_record["local_record"] != unsigned_record["local_record"]:
            raise EquivalenceError(f"local record differs: {_display_name(name)}")
        if signed_record["prefix_padding"] != unsigned_record["prefix_padding"]:
            raise EquivalenceError(f"alignment padding differs: {_display_name(name)}")

    return {
        "schema": "tvbox-apk-equivalence-v1",
        "status": "equivalent",
        "signed_sha256": signed_archive["sha256"],
        "unsigned_sha256": unsigned_archive["sha256"],
        "signed_size": signed_archive["size"],
        "unsigned_size": unsigned_archive["size"],
        "signed_entry_count": len(signed_records),
        "unsigned_entry_count": len(unsigned_records),
        "common_entry_count": len(unsigned_records),
        "signature_entries": [_display_name(name) for name in signed_only],
        "central_directory_offset": signed_archive["central_directory_offset"],
        "central_directory_size": signed_archive["central_directory_size"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signed", required=True, type=Path)
    parser.add_argument("--unsigned", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(compare_apks(args.signed, args.unsigned), sort_keys=True))
    except (OSError, EquivalenceError, struct.error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
