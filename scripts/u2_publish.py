#!/usr/bin/env python3
"""Focused GitHub Release state helpers for the U2 publish path."""

import json
import re

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
