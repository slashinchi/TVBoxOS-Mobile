#!/usr/bin/env python3
"""Stage the exact legacy Maven island for trusted GitHub Actions builds."""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


BASE_SOURCE = "https://maven.aliyun.com/repository/public"
MANIFEST_SCHEMA = "tvbox-legacy-dependencies-v1"
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)+$")
ALLOWED_COORDINATES = {
    ("com.hyman", "flowlayout-lib", "1.1.2"),
    ("com.kingja.loadsir", "loadsir", "1.3.8"),
    ("com.lzy.net", "okgo", "3.0.4"),
    ("com.owen", "tv-recyclerview", "3.0.0"),
}
MANIFEST_KEYS = {"schema", "source", "components"}
COMPONENT_KEYS = {
    "group",
    "module",
    "version",
    "packaging",
    "pom",
    "pom_sha256",
    "binary",
    "binary_sha256",
    "bootstrap_evidence",
}
EVIDENCE_KEYS = {"urls", "residual"}
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _xml_text(parent, name):
    for child in list(parent):
        if child.tag.rsplit("}", 1)[-1] == name:
            return (child.text or "").strip()
    return ""


def _safe_filename(value, expected):
    _require(value == expected, f"unexpected artifact filename: {value!r}")
    _require(Path(value).name == value and "/" not in value and "\\" not in value, "artifact filename must be a leaf")


def validate_manifest(manifest):
    _require(isinstance(manifest, dict), "manifest must be an object")
    _require(set(manifest) == MANIFEST_KEYS, "manifest has unexpected top-level fields")
    _require(manifest["schema"] == MANIFEST_SCHEMA, "unsupported manifest schema")
    _require(manifest["source"] == BASE_SOURCE, "manifest source must be the approved HTTPS transport")
    components = manifest["components"]
    _require(isinstance(components, list), "manifest components must be a list")

    seen = set()
    validated = []
    for component in components:
        _require(isinstance(component, dict), "manifest component must be an object")
        _require(set(component) == COMPONENT_KEYS, "manifest component has unexpected fields")
        group = component["group"]
        module = component["module"]
        version = component["version"]
        coordinate = (group, module, version)
        _require(all(isinstance(item, str) for item in coordinate), "coordinate fields must be strings")
        _require(TOKEN_RE.fullmatch(group or "") is not None, "invalid group")
        _require(TOKEN_RE.fullmatch(module or "") is not None, "invalid module")
        _require(VERSION_RE.fullmatch(version or "") is not None, "dynamic or invalid version")
        _require(coordinate in ALLOWED_COORDINATES, f"coordinate is outside the approved legacy island: {coordinate}")
        _require(coordinate not in seen, f"duplicate coordinate: {coordinate}")
        seen.add(coordinate)
        packaging = component["packaging"]
        _require(packaging in {"aar", "jar"}, "packaging must be aar or jar")
        expected_pom = f"{module}-{version}.pom"
        expected_binary = f"{module}-{version}.{packaging}"
        _safe_filename(component["pom"], expected_pom)
        _safe_filename(component["binary"], expected_binary)
        for field in ("pom_sha256", "binary_sha256"):
            _require(HEX64_RE.fullmatch(component[field] or "") is not None, f"{field} must be lowercase SHA-256")
        evidence = component["bootstrap_evidence"]
        _require(isinstance(evidence, dict) and set(evidence) == EVIDENCE_KEYS, "invalid bootstrap evidence")
        _require(
            isinstance(evidence["urls"], list)
            and evidence["urls"]
            and all(
                isinstance(url, str)
                and urllib.parse.urlparse(url).scheme == "https"
                and urllib.parse.urlparse(url).netloc
                for url in evidence["urls"]
            ),
            "bootstrap evidence must contain HTTPS URLs",
        )
        _require(evidence["residual"] == "single-source-byte-tofu", "bootstrap TOFU residual must be explicit")
        validated.append(component)

    _require(seen == ALLOWED_COORDINATES, "manifest must contain exactly the four approved legacy coordinates")
    return sorted(validated, key=lambda item: (item["group"], item["module"], item["version"]))


def load_manifest(path):
    manifest_path = Path(path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read manifest: {exc}") from exc
    validate_manifest(manifest)
    return manifest


def manifest_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_pom_bytes(data, component):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"invalid POM XML: {exc}") from exc
    _require(_xml_text(root, "groupId") == component["group"], "POM groupId mismatch")
    _require(_xml_text(root, "artifactId") == component["module"], "POM artifactId mismatch")
    _require(_xml_text(root, "version") == component["version"], "POM version mismatch")
    _require(_xml_text(root, "packaging") == component["packaging"], "POM packaging mismatch")
    dependencies = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "dependency":
            continue
        group = _xml_text(node, "groupId")
        module = _xml_text(node, "artifactId")
        version = _xml_text(node, "version")
        _require(TOKEN_RE.fullmatch(group or "") is not None, "POM dependency groupId is invalid")
        _require(TOKEN_RE.fullmatch(module or "") is not None, "POM dependency artifactId is invalid")
        _require(VERSION_RE.fullmatch(version or "") is not None, "POM dependency version is dynamic or invalid")
        dependencies.append((group, module, version))
    return dependencies


def _artifact_url(source, component, filename):
    group_path = component["group"].replace(".", "/")
    return f"{source}/{group_path}/{component['module']}/{component['version']}/{filename}"


def _fetch_bytes(url, opener=urllib.request.urlopen):
    request = urllib.request.Request(url, headers={"User-Agent": "TVBoxOS-Mobile-legacy-stager/1"})
    try:
        response = opener(request, timeout=30)
        with response:
            final_url = response.geturl()
            parsed = urllib.parse.urlparse(final_url)
            _require(
                final_url == url
                and parsed.scheme == "https"
                and parsed.netloc == "maven.aliyun.com",
                "download redirected outside the pinned source URL",
            )
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError(f"download failed for {url}: {exc}") from exc
    _require(len(data) <= MAX_DOWNLOAD_BYTES, f"download is too large: {url}")
    return data


def _verify_digest(data, expected, label):
    actual = hashlib.sha256(data).hexdigest()
    _require(actual == expected, f"{label} SHA-256 mismatch: expected {expected}, got {actual}")


def _relative_files(root):
    files = []
    directories = []
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            raise ValueError(f"staging layout contains symlink: {path}")
        if path.is_dir():
            directories.append(path.relative_to(root).as_posix())
        elif path.is_file():
            files.append(path.relative_to(root).as_posix())
        else:
            raise ValueError(f"staging layout contains unsupported entry: {path}")
    return set(files), set(directories)


def verify_staged_directory(manifest, root):
    components = validate_manifest(manifest)
    root = Path(root)
    _require(root.is_dir() and not root.is_symlink(), "staging root must be a real directory")
    files, directories = _relative_files(root)
    expected_files = set()
    expected_directories = {"."}
    for component in components:
        relative = Path(component["group"].replace(".", "/")) / component["module"] / component["version"]
        expected_directories.update(
            {
                relative.as_posix(),
                relative.parent.as_posix(),
                relative.parent.parent.as_posix(),
            }
        )
        pom_path = root / relative / component["pom"]
        binary_path = root / relative / component["binary"]
        expected_files.update({pom_path.relative_to(root).as_posix(), binary_path.relative_to(root).as_posix()})
        current = relative
        while current != Path("."):
            expected_directories.add(current.as_posix())
            current = current.parent
        _require(pom_path.is_file() and binary_path.is_file(), f"staged files missing for {component['module']}")
        pom_data = pom_path.read_bytes()
        binary_data = binary_path.read_bytes()
        _verify_digest(pom_data, component["pom_sha256"], f"{component['pom']}" )
        _verify_digest(binary_data, component["binary_sha256"], f"{component['binary']}" )
        validate_pom_bytes(pom_data, component)
    _require(files == expected_files, "staging file set differs from manifest")
    _require(directories == expected_directories, "staging directory set differs from manifest")
    return {"files": sorted(files), "manifest_sha256": None}


def stage_manifest(manifest, output, opener=urllib.request.urlopen):
    components = validate_manifest(manifest)
    output = Path(output)
    runner_temp = os.environ.get("RUNNER_TEMP")
    if runner_temp:
        _require(
            output.resolve().is_relative_to(Path(runner_temp).resolve()),
            "staging output must be under RUNNER_TEMP",
        )
    if output.exists() or output.is_symlink():
        _require(not output.is_symlink() and output.is_dir(), "staging output must be a new directory")
        _require(not any(output.iterdir()), "staging output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    try:
        for component in components:
            pom_url = _artifact_url(manifest["source"], component, component["pom"])
            binary_url = _artifact_url(manifest["source"], component, component["binary"])
            pom_data = _fetch_bytes(pom_url, opener)
            binary_data = _fetch_bytes(binary_url, opener)
            _verify_digest(pom_data, component["pom_sha256"], component["pom"])
            _verify_digest(binary_data, component["binary_sha256"], component["binary"])
            validate_pom_bytes(pom_data, component)
            relative = Path(component["group"].replace(".", "/")) / component["module"] / component["version"]
            destination = output / relative
            destination.mkdir(parents=True, exist_ok=True)
            (destination / component["pom"]).write_bytes(pom_data)
            (destination / component["binary"]).write_bytes(binary_data)
        verify_staged_directory(manifest, output)
        for path in sorted(output.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_symlink():
                raise ValueError(f"staging layout contains symlink: {path}")
            os.chmod(path, 0o555 if path.is_dir() else 0o444)
        os.chmod(output, 0o555)
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return {"files": sorted(str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()), "manifest_sha256": None}


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("stage", "verify"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--manifest", required=True, type=Path)
        subparser.add_argument("--output", required=True, type=Path)
    digest = subparsers.add_parser("manifest-digest")
    digest.add_argument("--manifest", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "manifest-digest":
            print(json.dumps({"manifest_sha256": manifest_sha256(args.manifest)}, sort_keys=True))
        elif args.command == "verify":
            result = verify_staged_directory(manifest, args.output)
            result["manifest_sha256"] = manifest_sha256(args.manifest)
            print(json.dumps(result, sort_keys=True))
        else:
            result = stage_manifest(manifest, args.output)
            result["manifest_sha256"] = manifest_sha256(args.manifest)
            print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
