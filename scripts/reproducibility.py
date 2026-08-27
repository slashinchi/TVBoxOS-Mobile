#!/usr/bin/env python3
"""Compare two clean RC builder evidence directories."""

import argparse
import hashlib
import json
from pathlib import Path


BUILD_EVIDENCE_FILES = (
    "unsigned.apk",
    "build-identity.json",
    "payload-manifest.json",
    "native-compat.json",
    "runtime-components.json",
    "legacy-dependencies.lock.json",
)
VOLATILE_IDENTITY_FIELDS = {
    "builder_role",
    "runner_image_version",
    "runner_image",
    "java_binary_path",
    "apksigner_path",
    "aapt2_path",
    "zipalign_path",
    "ndk_path",
}
IDENTITY_DIGEST_FIELDS = (
    "builder_recipe_sha256",
    "unsigned_sha256",
    "payload_manifest_sha256",
    "runtime_components_sha256",
    "legacy_manifest_sha256",
    "native_compat_report_sha256",
    "java_binary_sha256",
    "apksigner_sha256",
    "apksigner_jar_sha256",
    "aapt2_sha256",
    "zipalign_sha256",
    "llvm_readelf_sha256",
)
REQUIRED_IDENTITY_FIELDS = (
    "artifact_source_sha",
    "source_sha",
    "mode",
    "upstream_sha",
    "upstream_version",
    "upstream_code",
    "version_name",
    "version_code",
    "release_debt",
    "candidate_pr",
    "provenance_marker",
    "runner_image_os",
)
FILE_DIGEST_FIELDS = {
    "unsigned.apk": "unsigned_sha256",
    "payload-manifest.json": "payload_manifest_sha256",
    "native-compat.json": "native_compat_report_sha256",
    "runtime-components.json": "runtime_components_sha256",
    "legacy-dependencies.lock.json": "legacy_manifest_sha256",
}


class ReproducibilityError(ValueError):
    """Raised when clean builder evidence cannot be accepted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_root(root: Path) -> None:
    if root.is_symlink():
        raise ReproducibilityError(f"evidence root is a symlink: {root}")
    if not root.is_dir():
        raise ReproducibilityError(f"evidence root is not a directory: {root}")
    entries = list(root.iterdir())
    expected = set(BUILD_EVIDENCE_FILES)
    if len(entries) != len(expected) or {entry.name for entry in entries} != expected:
        raise ReproducibilityError("evidence root must contain exactly 6 regular files")
    for entry in entries:
        if entry.is_symlink():
            raise ReproducibilityError(f"evidence root contains symlink: {entry.name}")
        if not entry.is_file():
            raise ReproducibilityError("evidence root must contain exactly 6 regular files")


def _load_identity(root: Path) -> dict:
    try:
        identity = json.loads((root / "build-identity.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ReproducibilityError(f"invalid build identity: {exc}") from exc
    if not isinstance(identity, dict) or identity.get("schema") != "tvbox-release-identity-v2":
        raise ReproducibilityError("build identity schema mismatch")
    if identity.get("builder_role") not in {"primary", "repro"}:
        raise ReproducibilityError("build identity builder_role must be primary or repro")
    for field in REQUIRED_IDENTITY_FIELDS:
        if field not in identity or identity[field] is None:
            raise ReproducibilityError(f"required identity field: {field}")
    for field in IDENTITY_DIGEST_FIELDS:
        value = identity.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ReproducibilityError(f"invalid build identity digest: {field}")
    return identity


def _validate_file_digests(root: Path, identity: dict) -> None:
    for filename, field in FILE_DIGEST_FIELDS.items():
        actual = _sha256(root / filename)
        if identity.get(field) != actual:
            raise ReproducibilityError(f"{field} does not match {filename}")


def compare_build_evidence(
    primary_root: Path,
    repro_root: Path,
    *,
    primary_artifact_id: str,
    repro_artifact_id: str,
    primary_artifact_digest: str,
    repro_artifact_digest: str,
) -> dict:
    """Return a signed-gate report or raise for any mismatch."""

    if not primary_artifact_id or not repro_artifact_id:
        raise ReproducibilityError("artifact IDs are required")
    if primary_artifact_id == repro_artifact_id:
        raise ReproducibilityError("artifact IDs must differ")
    if not primary_artifact_digest or not repro_artifact_digest:
        raise ReproducibilityError("artifact digests are required")
    primary_root = Path(primary_root)
    repro_root = Path(repro_root)
    _validate_root(primary_root)
    _validate_root(repro_root)
    primary = _load_identity(primary_root)
    repro = _load_identity(repro_root)
    if primary["builder_role"] != "primary" or repro["builder_role"] != "repro":
        raise ReproducibilityError("builder_role must identify primary and repro artifacts")

    primary_files = {name: (primary_root / name).read_bytes() for name in BUILD_EVIDENCE_FILES if name != "build-identity.json"}
    repro_files = {name: (repro_root / name).read_bytes() for name in BUILD_EVIDENCE_FILES if name != "build-identity.json"}
    for filename, message in (
        ("unsigned.apk", "raw unsigned APK mismatch"),
        ("payload-manifest.json", "payload manifest mismatch"),
        ("runtime-components.json", "runtime dependency report mismatch"),
        ("native-compat.json", "native compatibility report mismatch"),
        ("legacy-dependencies.lock.json", "legacy dependency lock mismatch"),
    ):
        if primary_files[filename] != repro_files[filename]:
            raise ReproducibilityError(message)
    _validate_file_digests(primary_root, primary)
    _validate_file_digests(repro_root, repro)

    comparable_fields = (set(primary) | set(repro)) - VOLATILE_IDENTITY_FIELDS
    for field in sorted(comparable_fields):
        if primary.get(field) != repro.get(field):
            if field == "builder_recipe_sha256":
                raise ReproducibilityError("build recipe mismatch")
            if field.endswith("_sha256") and field not in FILE_DIGEST_FIELDS.values():
                raise ReproducibilityError(f"tool identity mismatch: {field}")
            raise ReproducibilityError(f"build identity mismatch: {field}")
    if primary.get("runner_image_os") != repro.get("runner_image_os"):
        raise ReproducibilityError("runner image OS mismatch")

    primary_unsigned = _sha256(primary_root / "unsigned.apk")
    report = {
        "schema": "tvbox-reproducibility-v1",
        "status": "equivalent",
        "primary_artifact_id": str(primary_artifact_id),
        "repro_artifact_id": str(repro_artifact_id),
        "primary_artifact_digest": str(primary_artifact_digest),
        "repro_artifact_digest": str(repro_artifact_digest),
        "primary_builder_role": primary["builder_role"],
        "repro_builder_role": repro["builder_role"],
        "primary_unsigned_sha256": primary_unsigned,
        "repro_unsigned_sha256": _sha256(repro_root / "unsigned.apk"),
        "builder_recipe_sha256": primary["builder_recipe_sha256"],
        "primary_runner_image_os": primary["runner_image_os"],
        "repro_runner_image_os": repro["runner_image_os"],
        "primary_runner_image_version": primary.get("runner_image_version", ""),
        "repro_runner_image_version": repro.get("runner_image_version", ""),
        "runner_image_drift": primary.get("runner_image_version") != repro.get("runner_image_version"),
        "compared_files": list(BUILD_EVIDENCE_FILES),
    }
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    compare = subparsers.add_parser("compare")
    compare.add_argument("--primary", type=Path, required=True)
    compare.add_argument("--repro", type=Path, required=True)
    compare.add_argument("--primary-artifact-id", required=True)
    compare.add_argument("--repro-artifact-id", required=True)
    compare.add_argument("--primary-artifact-digest", required=True)
    compare.add_argument("--repro-artifact-digest", required=True)
    compare.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = compare_build_evidence(
            args.primary,
            args.repro,
            primary_artifact_id=args.primary_artifact_id,
            repro_artifact_id=args.repro_artifact_id,
            primary_artifact_digest=args.primary_artifact_digest,
            repro_artifact_digest=args.repro_artifact_digest,
        )
        exit_code = 0
    except ReproducibilityError as exc:
        report = {"schema": "tvbox-reproducibility-v1", "status": "failed", "error": str(exc)}
        exit_code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
