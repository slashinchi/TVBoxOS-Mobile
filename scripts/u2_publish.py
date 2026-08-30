#!/usr/bin/env python3
"""Focused GitHub Release state helpers for the U2 publish path."""

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){3}$")
RELEASE_TAG_RE = re.compile(r"^v[0-9]+(?:\.[0-9]+){3}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
INCIDENT_REASON_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def expected_asset_set(version):
    """The exact public asset contract for a formal app release."""
    if not VERSION_RE.fullmatch(version or ""):
        raise ValueError("expected asset version must be numeric and dotted")
    return {f"TVBox-Mobile-v{version}.apk", "update.json"}


def _asset_digest(item):
    """Normalize an asset digest (accepts bare hex or sha256: prefix)."""
    raw = (item or {}).get("digest") or ""
    raw = raw.removeprefix("sha256:")
    return raw.lower()


def _require_full_sha(value, label):
    if not FULL_SHA_RE.fullmatch(value or ""):
        raise ValueError(f"{label} must be a full 40-char SHA")
    return value


def _require_hex64(value, label):
    if not HEX64_RE.fullmatch(value or ""):
        raise ValueError(f"{label} must be a 64-char hex digest")
    return value.lower()


def reconcile_draft_assets(draft, version, expected_digests=None):
    """Classify a draft asset set: exact / incomplete / unexpected / digest-mismatch."""
    expected = expected_asset_set(version)
    assets = (draft or {}).get("assets") or []
    names = [item.get("name") for item in assets]
    if len(names) != 2 or set(names) != expected:
        return "unexpected-asset" if len(names) > 2 else "incomplete"
    if expected_digests:
        for name in expected:
            actual = _asset_digest(next(item for item in assets if item["name"] == name))
            if not HEX64_RE.fullmatch(actual) or actual != (expected_digests.get(name) or "").lower():
                return "digest-mismatch"
    return "exact"


def reconcile_draft_decision(draft, version, expected_tag, expected_target_sha, apk_digest, update_digest, allow_nonstandard_tag=False):
    """Classify a draft for recovery.

    Returns one of:
      exact-reuse     — draft is identity-exact (isDraft + tag + target SHA) and
                        both present assets have exact digests.
      repair-missing  — identity-exact draft with only expected assets missing;
                        every *present* expected asset digest is exact; no
                        unexpected asset.
      reject-*        — identity-mismatch | not-draft | digest-mismatch |
                        asset-mismatch (extra/wrong asset) | empty-digest.
    Never returns a decision that would publish unverified bytes.
    """
    if not VERSION_RE.fullmatch(version or ""):
        return "reject-version"
    if not allow_nonstandard_tag and not RELEASE_TAG_RE.fullmatch(expected_tag or ""):
        return "reject-version"
    if not allow_nonstandard_tag and not expected_tag.startswith("v"):
        return "reject-version"
    _require_full_sha(expected_target_sha, "expected target SHA")
    _require_hex64(apk_digest, "APK digest")
    _require_hex64(update_digest, "update digest")

    tag = (draft or {}).get("tagName") or (draft or {}).get("tag_name")
    target = (draft or {}).get("targetCommitish") or (draft or {}).get("target_commitish")
    # Identity authority: the resolved tag-object commit SHA. A bare
    # targetCommitish that is a branch name (e.g. "main") is not identity.
    target_sha = (draft or {}).get("tagTargetSha") or (draft or {}).get("tag_target_sha") or ""
    if not target_sha and target:
        # Drafts have no tag ref; GitHub stores the exact --target SHA in
        # target_commitish when the release was created with a full SHA.
        if FULL_SHA_RE.fullmatch(target or ""):
            target_sha = target
    if tag != expected_tag or target_sha != expected_target_sha:
        return "reject-identity"
    if target not in ("", expected_target_sha):
        # targetCommitish must be the exact full SHA (U2 created the draft with
        # --target <sha>); a branch name or any other ref is never identity and
        # is rejected even when a tagTargetSha is present.
        return "reject-identity"
    if (draft or {}).get("isDraft", (draft or {}).get("draft")) is not True:
        return "reject-not-draft"

    expected = expected_asset_set(version)
    assets = {(item.get("name") or ""): _asset_digest(item) for item in (draft or {}).get("assets") or []}
    names = set(assets)
    if names - expected:
        return "reject-extra-asset"
    if any(not HEX64_RE.fullmatch(digest) for digest in assets.values()):
        return "reject-digest-mismatch"

    apk_name = f"TVBox-Mobile-v{version}.apk"
    present_apk = assets.get(apk_name, "")
    present_update = assets.get("update.json", "")
    apk_ok = (present_apk == "" or present_apk == apk_digest)
    update_ok = (present_update == "" or present_update == update_digest)
    if not apk_ok or not update_ok:
        return "reject-digest-mismatch"
    if names == expected:
        return "exact-reuse"
    return "repair-missing"


def immutable_verified(state, expected_tag=None, expected_target=None):
    """True only when the published Release is immutable, at the exact SHA, with the exact asset count."""
    if not isinstance(state, dict):
        return False
    if state.get("immutable") is not True:
        return False
    if not RELEASE_TAG_RE.fullmatch(state.get("tag") or ""):
        return False
    if not FULL_SHA_RE.fullmatch(state.get("target") or ""):
        return False
    if expected_tag is not None and state.get("tag") != expected_tag:
        return False
    if expected_target is not None and state.get("target") != expected_target:
        return False
    if state.get("asset_count") != 2:
        return False
    return True


def released_identity_decision(release, version, expected_tag, expected_target_sha, apk_digest, update_digest):
    """Classify an already-published (non-draft) Release for retry recovery.

    Returns one of:
      verify-published        — the published Release is identity-exact at the
                                expected tag + target SHA with exact two-asset
                                digests (or missing-only assets that can be
                                repaired before metadata reconciliation).
      reject-published-*      — identity-mismatch | digest-mismatch |
                                extra-asset | empty-digest | invalid-shape.
    Never returns a decision that would publish unverified bytes. This path is
    reached only when a prior run already crossed the publish point (e.g. the
    Release is immutable/published but delivery, metadata or readback failed).
    """
    if not VERSION_RE.fullmatch(version or ""):
        return "reject-version"
    if not RELEASE_TAG_RE.fullmatch(expected_tag or ""):
        return "reject-version"
    if not expected_tag.startswith("v"):
        return "reject-version"
    _require_full_sha(expected_target_sha, "expected target SHA")
    _require_hex64(apk_digest, "APK digest")
    _require_hex64(update_digest, "update digest")

    if not isinstance(release, dict):
        return "reject-published-invalid-shape"
    tag = release.get("tagName") or release.get("tag_name")
    target = release.get("targetCommitish") or release.get("target_commitish")
    # The tag object SHA is the identity authority for a published Release
    # (target_commitish may be a branch name after publish; never trust it alone).
    target_sha = release.get("tagTargetSha") or release.get("tag_target_sha") or ""
    if not target_sha and target:
        if FULL_SHA_RE.fullmatch(target or ""):
            target_sha = target
    if tag != expected_tag or target_sha != expected_target_sha:
        return "reject-published-identity"
    if (release.get("isDraft", release.get("draft", False)) is True):
        return "reject-published-is-draft"
    expected = expected_asset_set(version)
    assets = {(item.get("name") or ""): _asset_digest(item) for item in release.get("assets") or []}
    names = set(assets)
    if names - expected:
        return "reject-published-extra-asset"
    if any(not HEX64_RE.fullmatch(digest) for digest in assets.values()):
        return "reject-published-digest-mismatch"
    apk_name = f"TVBox-Mobile-v{version}.apk"
    present_apk = assets.get(apk_name, "")
    present_update = assets.get("update.json", "")
    apk_ok = (present_apk == "" or present_apk == apk_digest)
    update_ok = (present_update == "" or present_update == update_digest)
    if not apk_ok or not update_ok:
        return "reject-published-digest-mismatch"
    if names == expected:
        return "verify-published"
    # A published Release in an immutable repository can never accept new
    # assets: `gh release upload` fails on immutable published Releases.
    # Missing assets on a published Release are therefore unrecoverable and
    # must fail closed (never "repair" a public immutable Release).
    return "reject-published-missing-asset"


def verify_release_assets(release, version, expected_digests, download_dir):
    """Verify API-reported digests and actual downloaded bytes for both assets.

    Returns {"verified": bool, "checked": [names...]}.
    Fails closed on missing/extra asset, missing/malformed digest, or
    downloaded-byte digest mismatch against the expected (local) digest.
    """
    expected = expected_asset_set(version)
    assets = {(item.get("name") or ""): _asset_digest(item) for item in (release or {}).get("assets") or []}
    names = set(assets)
    if names != expected:
        return {"verified": False, "checked": [], "reason": "asset-set-mismatch"}
    if any(not HEX64_RE.fullmatch(digest) for digest in assets.values()):
        return {"verified": False, "checked": [], "reason": "missing-digest"}
    if any(assets[name].lower() != (expected_digests.get(name) or "").lower() for name in expected):
        return {"verified": False, "checked": [], "reason": "api-digest-mismatch"}

    out_dir = Path(download_dir)
    checked = []
    for name in sorted(expected):
        target = out_dir / name
        if not target.is_file():
            return {"verified": False, "checked": checked, "reason": f"missing-download:{name}"}
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != (expected_digests[name] or "").lower():
            return {"verified": False, "checked": checked, "reason": f"byte-mismatch:{name}"}
        checked.append(name)
    return {"verified": True, "checked": checked, "reason": ""}


def verify_remote_metadata(metadata_bytes, expected_version, expected_apk_url):
    """Byte-exact remote metadata readback."""
    try:
        payload = json.loads(metadata_bytes.decode("utf-8"))
    except Exception:
        return {"verified": False, "reason": "invalid-json"}
    if not isinstance(payload, dict):
        return {"verified": False, "reason": "invalid-shape"}
    if payload.get("version") != expected_version:
        return {"verified": False, "reason": "version-mismatch"}
    if payload.get("apk_url") != expected_apk_url:
        return {"verified": False, "reason": "url-mismatch"}
    canonical = json.dumps(build_update_json(expected_version, expected_apk_url), sort_keys=True) + "\n"
    if metadata_bytes.decode("utf-8") != canonical:
        return {"verified": False, "reason": "byte-mismatch"}
    return {"verified": True, "reason": ""}


def monotonic_metadata_next(current, candidate):
    """Forward-only metadata reconciliation: never roll back to an older version."""
    cur_version = (current or {}).get("version") or ""
    cand_version = (candidate or {}).get("version") or ""

    def key(version):
        return tuple(int(part) for part in version.split("."))

    if cur_version and cand_version and key(cand_version) < key(cur_version):
        return current
    return candidate


def verify_delivery_url(url, expected_sha256, fetched_sha256):
    """The delivered bytes at the proxy URL must equal the exact signed RC digest."""
    if not url:
        return False
    if not HEX64_RE.fullmatch(expected_sha256 or ""):
        return False
    if not HEX64_RE.fullmatch(fetched_sha256 or ""):
        return False
    return fetched_sha256.lower() == expected_sha256.lower()


def build_update_json(version, apk_url):
    """The canonical root update.json payload for a formal release."""
    if not VERSION_RE.fullmatch(version or ""):
        raise ValueError("update version must be a 4-part numeric version")
    if not apk_url.startswith("https://"):
        raise ValueError("update apk_url must be https")
    return {"version": version, "apk_url": apk_url}


def extract_signed_apk(zip_path, output_dir):
    """Extract the signed.apk member from an Actions artifact zip."""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        signed = next((n for n in names if n.endswith("signed.apk")), None)
        if signed is None:
            raise ValueError("artifact zip has no signed.apk")
        z.extract(signed, output_dir)
    return str(Path(output_dir) / signed)


def incident_key(mode, source_sha, version, debt):
    """Identity-bound incident key: mode + source SHA + version + debt fingerprint."""
    if not INCIDENT_REASON_RE.fullmatch(mode or ""):
        raise ValueError("mode must be lowercase-hyphen")
    _require_full_sha(source_sha, "source SHA")
    if not VERSION_RE.fullmatch(version or ""):
        raise ValueError("version must be 4-part numeric")
    _require_hex64(debt, "debt fingerprint")
    return f"{mode}:{source_sha}:{version}:{debt}"


def incident_satisfied(incident, release_tag, release_target_sha, version, debt, delivery_ok):
    """Whether an incident's release-condition is satisfied (close-able).

    For release-delivery holds the incident closes only when delivery verifies.
    For other releases the incident closes when the exact tag/target/version/debt
    are confirmed and no further mutation is pending.
    """
    if not isinstance(incident, dict):
        return False
    if incident.get("release_tag") != release_tag:
        return False
    if incident.get("release_target_sha") != release_target_sha:
        return False
    if incident.get("version") != version:
        return False
    if incident.get("debt") != debt:
        return False
    if incident.get("kind") == "release-delivery":
        return delivery_ok is True
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract-signed-apk")
    extract.add_argument("--zip", required=True)
    extract.add_argument("--output-dir", required=True)

    update = subparsers.add_parser("build-update-json")
    update.add_argument("--version", required=True)
    update.add_argument("--apk-url", required=True)
    update.add_argument("--output", required=True)

    monotonic = subparsers.add_parser("monotonic-compare")
    monotonic.add_argument("--current-version", required=True)
    monotonic.add_argument("--candidate-version", required=True)

    delivery = subparsers.add_parser("delivery-compare")
    delivery.add_argument("--url", required=True)
    delivery.add_argument("--expected-sha", required=True)
    delivery.add_argument("--fetched-sha", required=True)

    reconcile = subparsers.add_parser("reconcile-draft")
    reconcile.add_argument("--draft", required=True)
    reconcile.add_argument("--version", required=True)
    reconcile.add_argument("--expected-tag", required=True)
    reconcile.add_argument("--expected-target-sha", required=True)
    reconcile.add_argument("--apk-digest", required=True)
    reconcile.add_argument("--update-digest", required=True)
    reconcile.add_argument("--allow-nonstandard-tag", action="store_true",
                           help="allow u2-canary-* tags (disposable harness only; production stays strict)")

    verify_assets = subparsers.add_parser("verify-release-assets")
    verify_assets.add_argument("--release", required=True)
    verify_assets.add_argument("--version", required=True)
    verify_assets.add_argument("--apk-digest", required=True)
    verify_assets.add_argument("--update-digest", required=True)
    verify_assets.add_argument("--download-dir", required=True)

    verify_meta = subparsers.add_parser("verify-remote-metadata")
    verify_meta.add_argument("--metadata-file", required=True)
    verify_meta.add_argument("--expected-version", required=True)
    verify_meta.add_argument("--expected-apk-url", required=True)

    released = subparsers.add_parser("released-identity")
    released.add_argument("--release", required=True)
    released.add_argument("--version", required=True)
    released.add_argument("--expected-tag", required=True)
    released.add_argument("--expected-target-sha", required=True)
    released.add_argument("--apk-digest", required=True)
    released.add_argument("--update-digest", required=True)

    incident = subparsers.add_parser("incident-key")
    incident.add_argument("--mode", required=True)
    incident.add_argument("--source-sha", required=True)
    incident.add_argument("--version", required=True)
    incident.add_argument("--debt", required=True)

    args = parser.parse_args(argv)
    if args.command == "extract-signed-apk":
        print(extract_signed_apk(args.zip, args.output_dir))
    elif args.command == "build-update-json":
        payload = build_update_json(args.version, args.apk_url)
        Path(args.output).write_text(json.dumps(payload, sort_keys=True) + "\n")
        print(json.dumps(payload, sort_keys=True))
    elif args.command == "monotonic-compare":
        if not VERSION_RE.fullmatch(args.candidate_version or ""):
            raise SystemExit("candidate version must be 4-part numeric")
        if not VERSION_RE.fullmatch(args.current_version or "") and (args.current_version or ""):
            raise SystemExit("current version must be 4-part numeric or empty")
        if not (args.current_version or ""):
            print(json.dumps({"newer": True, "current": "", "candidate": args.candidate_version}, sort_keys=True))
            return 0
        cur = tuple(int(p) for p in args.current_version.split("."))
        cand = tuple(int(p) for p in args.candidate_version.split("."))
        print(json.dumps({"newer": cand >= cur, "current": args.current_version, "candidate": args.candidate_version}, sort_keys=True))
    elif args.command == "delivery-compare":
        print(json.dumps({"verified": verify_delivery_url(args.url, args.expected_sha, args.fetched_sha)}, sort_keys=True))
    elif args.command == "reconcile-draft":
        draft = json.loads(args.draft)
        decision = reconcile_draft_decision(
            draft,
            args.version,
            args.expected_tag,
            args.expected_target_sha,
            args.apk_digest,
            args.update_digest,
            allow_nonstandard_tag=args.allow_nonstandard_tag,
        )
        print(json.dumps({"decision": decision, "reuse": decision == "exact-reuse"}, sort_keys=True))
    elif args.command == "verify-release-assets":
        release = json.loads(args.release)
        print(json.dumps(verify_release_assets(
            release,
            args.version,
            {f"TVBox-Mobile-v{args.version}.apk": args.apk_digest, "update.json": args.update_digest},
            args.download_dir,
        ), sort_keys=True))
    elif args.command == "verify-remote-metadata":
        print(json.dumps(verify_remote_metadata(
            Path(args.metadata_file).read_bytes(),
            args.expected_version,
            args.expected_apk_url,
        ), sort_keys=True))
    elif args.command == "released-identity":
        release = json.loads(args.release)
        decision = released_identity_decision(
            release,
            args.version,
            args.expected_tag,
            args.expected_target_sha,
            args.apk_digest,
            args.update_digest,
        )
        print(json.dumps({"decision": decision}, sort_keys=True))
    elif args.command == "incident-key":
        print(json.dumps({"key": incident_key(args.mode, args.source_sha, args.version, args.debt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
