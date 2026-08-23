#!/usr/bin/env python3
"""Characterize packaged 64-bit ELF alignment without modifying native bytes."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ELF_PATH_RE = re.compile(r"^lib/(arm64-v8a|x86_64)/[^/]+\.so$")
LOAD_RE = re.compile(r"^\s*LOAD\s+.*\s(0x[0-9a-fA-F]+|[0-9]+)\s*$")
RELRO_RE = re.compile(r"^\s*GNU_RELRO\s+")
MIN_16K_ALIGNMENT = 0x4000
KNOWN_INCOMPATIBLE_PATHS = {
    "lib/arm64-v8a/libconscrypt_jni.so",
    "lib/arm64-v8a/libquickjs-android-wrapper.so",
    "lib/arm64-v8a/librtmp-jni.so",
}


def parse_readelf_program_headers(text, path):
    alignments = []
    relro = False
    for line in text.splitlines():
        load_match = LOAD_RE.match(line)
        if load_match:
            alignments.append(int(load_match.group(1), 0))
        if RELRO_RE.match(line):
            relro = True
    if not alignments:
        raise ValueError(f"ELF has no PT_LOAD program header: {path}")
    minimum = min(alignments)
    return {
        "path": path,
        "min_load_align": minimum,
        "relro": relro,
        "compatible": all(value >= MIN_16K_ALIGNMENT for value in alignments),
    }


def summarize_report(components):
    if not components:
        raise ValueError("APK contains no packaged 64-bit ELF libraries")
    incompatible = sorted(item["path"] for item in components if not item["compatible"])
    incompatible_set = set(incompatible)
    if incompatible_set not in (set(), KNOWN_INCOMPATIBLE_PATHS):
        unexpected = sorted(incompatible_set ^ KNOWN_INCOMPATIBLE_PATHS)
        raise ValueError(f"unexpected native compatibility debt: {unexpected}")
    return {
        "status": "known-debt" if incompatible else "clean",
        "incompatible_count": len(incompatible),
        "incompatible_paths": incompatible,
    }


def inspect_apk(apk, llvm_readelf):
    apk = Path(apk)
    try:
        archive = zipfile.ZipFile(apk)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"cannot read APK: {exc}") from exc
    with archive:
        paths = [info.filename for info in archive.infolist() if ELF_PATH_RE.fullmatch(info.filename)]
        if len(paths) != len(set(paths)):
            raise ValueError("APK contains duplicate native library paths")
        components = []
        with tempfile.TemporaryDirectory(prefix="tvbox-native-") as temp:
            temp_root = Path(temp)
            for index, path in enumerate(sorted(paths)):
                native_path = temp_root / f"native-{index}.so"
                native_path.write_bytes(archive.read(path))
                try:
                    result = subprocess.run(
                        [str(llvm_readelf), "-lW", str(native_path)],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                except (OSError, subprocess.CalledProcessError) as exc:
                    raise ValueError(f"cannot inspect ELF {path}: {exc}") from exc
                components.append(parse_readelf_program_headers(result.stdout, path))
    return sorted(components, key=lambda item: item["path"])


def canonical_report(components):
    return {
        "schema": "tvbox-native-compat-v1",
        "min_required_load_align": MIN_16K_ALIGNMENT,
        "components": components,
    }


def write_report(report, output):
    output = Path(output)
    output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--llvm-readelf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        components = inspect_apk(args.apk, args.llvm_readelf)
        report = canonical_report(components)
        summary = summarize_report(components)
        report_sha256 = write_report(report, args.output)
        print(json.dumps({"report_sha256": report_sha256, **summary}, sort_keys=True, separators=(",", ":")))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
