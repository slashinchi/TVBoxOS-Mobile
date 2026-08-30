#!/usr/bin/env python3
"""Focused GitHub Release state helpers for the U2 publish path."""

import argparse
import json
import re
import zipfile
from pathlib import Path

VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){3}$")
RELEASE_TAG_RE = re.compile(r"^v[0-9]+(?:\.[0-9]+){3}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def expected_asset_set(version):
    """The exact public asset contract for a formal app release."""
    if not VERSION_RE.fullmatch(version or ""):
        raise ValueError("expected asset version must be numeric and dotted")
    return {f"TVBox-Mobile-v{version}.apk", "update.json"}


def reconcile_draft_assets(draft, version, expected_digests=None):
    """Classify a draft asset set: exact / incomplete / unexpected / digest-mismatch."""
    expected = expected_asset_set(version)
    assets = (draft or {}).get("assets") or []
    names = [item.get("name") for item in assets]
    if len(names) != 2 or set(names) != expected:
        return "unexpected-asset" if len(names) > 2 else "incomplete"
    if expected_digests:
        for name in expected:
            actual = (next(item["digest"] for item in assets if item["name"] == name) or "").lower()
            if not HEX64_RE.fullmatch(actual) or actual != (expected_digests.get(name) or "").lower():
                return "digest-mismatch"
    return "exact"


def immutable_verified(state, expected_tag=None, expected_target=None):
    """True only when the published Release is immutable, at the exact SHA, with the exact asset count."""
    if not isinstance(state, dict):
        return False
    if state.get("immutable") is not True:
        return False
    if not RELEASE_TAG_RE.fullmatch(state.get("tag") or ""):
        return False
    if not re.fullmatch(r"[0-9a-f]{40}", state.get("target") or ""):
        return False
    if expected_tag is not None and state.get("tag") != expected_tag:
        return False
    if expected_target is not None and state.get("target") != expected_target:
        return False
    if state.get("asset_count") != 2:
        return False
    return True


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
    reconcile.add_argument("--expected-target", required=True)
    reconcile.add_argument("--apk-digest", required=True)
    reconcile.add_argument("--update-digest", required=True)

    args = parser.parse_args(argv)
    if args.command == "extract-signed-apk":
        print(extract_signed_apk(args.zip, args.output_dir))
    elif args.command == "build-update-json":
        payload = build_update_json(args.version, args.apk_url)
        Path(args.output).write_text(json.dumps(payload, sort_keys=True) + "\n")
        print(json.dumps(payload, sort_keys=True))
    elif args.command == "monotonic-compare":
        if not VERSION_RE.fullmatch(args.current_version or "") or not VERSION_RE.fullmatch(args.candidate_version or ""):
            raise SystemExit("versions must be 4-part numeric")
        cur = tuple(int(p) for p in args.current_version.split("."))
        cand = tuple(int(p) for p in args.candidate_version.split("."))
        print(json.dumps({"newer": cand >= cur, "current": args.current_version, "candidate": args.candidate_version}, sort_keys=True))
    elif args.command == "delivery-compare":
        print(json.dumps({"verified": verify_delivery_url(args.url, args.expected_sha, args.fetched_sha)}, sort_keys=True))
    elif args.command == "reconcile-draft":
        draft = json.loads(args.draft)
        tag = draft.get("tagName") or draft.get("tag_name")
        target = draft.get("targetCommitish") or draft.get("target_commitish")
        if tag != args.expected_tag or target != args.expected_target:
            print(json.dumps({"reuse": False, "reason": "identity-mismatch"}, sort_keys=True))
        else:
            assets = {
                item["name"]: (item.get("digest") or "").removeprefix("sha256:").lower()
                for item in (draft.get("assets") or [])
            }
            expected = expected_asset_set(args.version)
            names = set(assets)
            if names - expected:
                print(json.dumps({"reuse": False, "reason": "asset-mismatch"}, sort_keys=True))
            elif names == expected:
                apk_ok = assets.get(f"TVBox-Mobile-v{args.version}.apk", "") == args.apk_digest.lower()
                update_ok = assets.get("update.json", "") == args.update_digest.lower() if args.update_digest else True
                if apk_ok and update_ok:
                    print(json.dumps({"reuse": True, "reason": "exact"}, sort_keys=True))
                else:
                    print(json.dumps({"reuse": False, "reason": "incomplete"}, sort_keys=True))
            else:
                print(json.dumps({"reuse": False, "reason": "incomplete"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
