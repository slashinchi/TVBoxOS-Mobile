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
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
NFF_HINTS = {
    "hint: Updates were rejected because the remote contains work that you do not",
    "hint: have locally. This is usually caused by another repository pushing",
    "hint: have locally. This is usually caused by another repository pushing to",
    "hint: the same ref. You may want to first integrate the remote changes",
    "hint: the same ref. If you want to integrate the remote changes use",
    "hint: the same ref. If you want to integrate the remote changes, use",
    "hint: (e.g., 'git pull ...') before pushing again.",
    "hint: 'git pull ...') before pushing again.",
    "hint: 'git pull' before pushing again.",
    "hint: See the 'Note about fast-forwards' in 'git push --help' for details.",
}


def _reject_duplicate_object_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def strict_json_loads(value):
    """Parse JSON without silently accepting duplicate object keys."""
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("JSON must be valid UTF-8") from exc
    if not isinstance(value, str):
        raise ValueError("JSON input must be text or UTF-8 bytes")
    try:
        return json.loads(value, object_pairs_hook=_reject_duplicate_object_keys)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON") from exc

VERIFIED_RELEASE_FIELDS = (
    "tag",
    "target",
    "versionName",
    "versionCode",
    "assetSha256",
    "updateSha256",
    "signerSha256",
    "sourceSha",
    "debt",
    "runId",
    "runAttempt",
    "verified",
    "tag_ancestor",
)
VERIFIED_RELEASE_STABLE_FIELDS = tuple(
    field for field in VERIFIED_RELEASE_FIELDS if field != "runAttempt"
)
LEGACY_RELEASE_FIELDS = (
    "tag",
    "target",
    "versionName",
    "versionCode",
    "assetSha256",
    "signerSha256",
    "verified",
    "tag_ancestor",
)


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
    if not isinstance(value, str) or not FULL_SHA_RE.fullmatch(value):
        raise ValueError(f"{label} must be a full 40-char SHA")
    return value


def _require_hex64(value, label):
    if not isinstance(value, str) or not HEX64_RE.fullmatch(value):
        raise ValueError(f"{label} must be a 64-char hex digest")
    return value.lower()


def _require_positive_integer(value, label):
    text = str(value)
    if isinstance(value, bool) or not RUN_ID_RE.fullmatch(text):
        raise ValueError(f"{label} must be a positive integer")
    return int(text)


def verified_release_entry(
    tag,
    target,
    version_name,
    version_code,
    asset_sha256,
    update_sha256,
    signer_sha256,
    source_sha,
    debt,
    run_id,
    run_attempt,
):
    """Build the complete immutable identity persisted for a verified Release."""
    if not isinstance(tag, str) or not RELEASE_TAG_RE.fullmatch(tag):
        raise ValueError("verified release tag must be a formal v* tag")
    if not isinstance(version_name, str) or not VERSION_RE.fullmatch(version_name):
        raise ValueError("verified release version must be 4-part numeric")
    if tag != f"v{version_name}":
        raise ValueError("verified release tag/version mismatch")
    _require_full_sha(target, "verified release target SHA")
    _require_full_sha(source_sha, "verified release source SHA")
    code = _require_positive_integer(version_code, "verified release versionCode")
    _require_hex64(asset_sha256, "verified release APK SHA-256")
    _require_hex64(update_sha256, "verified release update SHA-256")
    _require_hex64(signer_sha256, "verified release signer SHA-256")
    _require_hex64(debt, "verified release debt fingerprint")
    run = str(_require_positive_integer(run_id, "verified release run ID"))
    attempt = str(_require_positive_integer(run_attempt, "verified release run attempt"))
    return {
        "tag": tag,
        "target": target,
        "versionName": version_name,
        "versionCode": code,
        "assetSha256": asset_sha256.lower(),
        "updateSha256": update_sha256.lower(),
        "signerSha256": signer_sha256.lower(),
        "sourceSha": source_sha,
        "debt": debt.lower(),
        "runId": run,
        "runAttempt": attempt,
        "verified": True,
        "tag_ancestor": True,
    }


def _validate_verified_release_entry(entry):
    if not isinstance(entry, dict) or set(entry) != set(VERIFIED_RELEASE_FIELDS):
        raise ValueError("malformed verified release entry")
    expected = verified_release_entry(
        tag=entry["tag"],
        target=entry["target"],
        version_name=entry["versionName"],
        version_code=entry["versionCode"],
        asset_sha256=entry["assetSha256"],
        update_sha256=entry["updateSha256"],
        signer_sha256=entry["signerSha256"],
        source_sha=entry["sourceSha"],
        debt=entry["debt"],
        run_id=entry["runId"],
        run_attempt=entry["runAttempt"],
    )
    if entry != expected:
        raise ValueError("verified release entry is not canonical")
    return entry


def _validate_ledger_entry(entry):
    if not isinstance(entry, dict):
        raise ValueError("verified release ledger entry must be an object")
    if set(entry) == set(VERIFIED_RELEASE_FIELDS):
        return _validate_verified_release_entry(entry)
    if set(entry) != set(LEGACY_RELEASE_FIELDS):
        raise ValueError("malformed verified release ledger entry")
    if not RELEASE_TAG_RE.fullmatch(entry.get("tag") or ""):
        raise ValueError("legacy verified release tag is invalid")
    if not VERSION_RE.fullmatch(entry.get("versionName") or ""):
        raise ValueError("legacy verified release version is invalid")
    if entry["tag"] != f"v{entry['versionName']}":
        raise ValueError("legacy verified release tag/version mismatch")
    _require_full_sha(entry.get("target"), "legacy verified release target SHA")
    if isinstance(entry.get("versionCode"), bool) or not isinstance(entry.get("versionCode"), int):
        raise ValueError("legacy verified release versionCode must be an integer")
    _require_positive_integer(entry.get("versionCode"), "legacy verified release versionCode")
    _require_hex64(entry.get("assetSha256"), "legacy verified release APK SHA-256")
    _require_hex64(entry.get("signerSha256"), "legacy verified release signer SHA-256")
    if entry.get("verified") is not True or entry.get("tag_ancestor") is not True:
        raise ValueError("legacy verified release flags must be true")
    return entry


def _validate_ledger(ledger):
    if not isinstance(ledger, list):
        raise ValueError("verified release ledger must be a JSON array")
    identities = set()
    tags = set()
    versions = set()
    version_codes = set()
    targets = set()
    previous_version = None
    previous_version_code = None
    complete_seen = False
    for entry in ledger:
        validated = _validate_ledger_entry(entry)
        fields = set(validated)
        if complete_seen and fields == set(LEGACY_RELEASE_FIELDS):
            raise ValueError("legacy verified release entry after complete identity")
        if fields == set(VERIFIED_RELEASE_FIELDS):
            complete_seen = True
        version = tuple(int(part) for part in validated["versionName"].split("."))
        version_code = validated["versionCode"]
        if previous_version is not None and (
            version <= previous_version or version_code <= previous_version_code
        ):
            raise ValueError("verified release ledger is not strictly increasing")
        identity = (validated["tag"], validated["versionName"], validated["target"])
        if (
            identity in identities
            or validated["tag"] in tags
            or validated["versionName"] in versions
            or validated["versionCode"] in version_codes
            or validated["target"] in targets
        ):
            raise ValueError("duplicate verified release identity")
        identities.add(identity)
        tags.add(validated["tag"])
        versions.add(validated["versionName"])
        version_codes.add(validated["versionCode"])
        targets.add(validated["target"])
        previous_version = version
        previous_version_code = version_code
    return ledger


def reconcile_verified_releases(ledger, entry):
    """Reconcile one verified identity without rewriting a conflicting release."""
    _validate_ledger(ledger)
    _validate_verified_release_entry(entry)
    identity = (entry["tag"], entry["versionName"], entry["target"])
    for existing in ledger:
        existing_identity = (
            existing.get("tag"),
            existing.get("versionName"),
            existing.get("target"),
        )
        if existing == entry:
            return {"action": "exact-reuse", "ledger": list(ledger)}
        if all(existing.get(field) == entry[field] for field in VERIFIED_RELEASE_STABLE_FIELDS):
            # A rerun can have a new workflow attempt after the Release already
            # exists. Preserve the first durable run identity and reuse it.
            return {"action": "exact-reuse", "ledger": list(ledger)}
        if (
            existing_identity == identity
            or existing.get("tag") == entry["tag"]
            or existing.get("versionName") == entry["versionName"]
            or existing.get("versionCode") == entry["versionCode"]
            or existing.get("target") == entry["target"]
        ):
            raise ValueError("verified release identity conflict")

    versions = [
        tuple(int(part) for part in existing["versionName"].split("."))
        for existing in ledger
    ]
    version_codes = [int(existing["versionCode"]) for existing in ledger]
    candidate_version = tuple(int(part) for part in entry["versionName"].split("."))
    if versions and candidate_version < max(versions):
        raise ValueError("verified release version is not monotonic")
    if version_codes and entry["versionCode"] <= max(version_codes):
        raise ValueError("verified release versionCode is not monotonic")
    return {"action": "append", "ledger": [*ledger, dict(entry)]}


def parse_update_metadata(metadata_bytes):
    """Parse and semantically validate the strict two-field update manifest."""
    payload = strict_json_loads(metadata_bytes)
    if not isinstance(payload, dict) or set(payload) != {"version", "apk_url"}:
        raise ValueError("update metadata must contain exactly version and apk_url")
    build_update_json(payload["version"], payload["apk_url"])
    return payload


def reconcile_verified_release_metadata(
    current_update_bytes,
    current_ledger_bytes,
    candidate_update_bytes,
    entry,
):
    """Read and reconcile both metadata blobs without mutating either input."""
    current = parse_update_metadata(current_update_bytes)
    candidate = parse_update_metadata(candidate_update_bytes)
    ledger = strict_json_loads(current_ledger_bytes)
    _validate_ledger(ledger)
    _validate_verified_release_entry(entry)
    if not isinstance(current_update_bytes, (bytes, bytearray)) or not isinstance(
        candidate_update_bytes, (bytes, bytearray)
    ):
        raise ValueError("metadata update blobs must be bytes")
    if ledger and "updateSha256" in ledger[-1]:
        if hashlib.sha256(current_update_bytes).hexdigest() != ledger[-1]["updateSha256"]:
            raise ValueError("current update metadata digest does not match latest verified release")
    if candidate["version"] != entry["versionName"]:
        raise ValueError("candidate update version does not match verified release entry")
    if hashlib.sha256(candidate_update_bytes).hexdigest() != entry["updateSha256"]:
        raise ValueError("candidate update digest does not match verified release entry")

    current_version = tuple(int(part) for part in current["version"].split("."))
    candidate_version = tuple(int(part) for part in candidate["version"].split("."))
    if candidate_version < current_version:
        raise ValueError("candidate update version is not monotonic")
    if candidate_version == current_version and candidate != current:
        raise ValueError("same-version update metadata has a different identity")
    if ledger and current["version"] != ledger[-1]["versionName"]:
        raise ValueError("update metadata does not match the latest verified release")

    result = reconcile_verified_releases(ledger, entry)
    return {
        "action": result["action"],
        "ledger": result["ledger"],
        "current": current,
        "candidate": candidate,
    }


def classify_metadata_push(
    push_status,
    porcelain_status,
    local_parent,
    remote_head_before,
    remote_head_after,
    attempt,
    max_attempts,
):
    """Classify a normal metadata push using status and fresh remote refs."""
    if isinstance(push_status, bool) or not isinstance(push_status, int) or push_status < 0:
        raise ValueError("push status must be a non-negative integer")
    _require_full_sha(local_parent, "local metadata parent")
    _require_full_sha(remote_head_before, "remote metadata head before push")
    _require_full_sha(remote_head_after, "remote metadata head after push")
    attempt = _require_positive_integer(attempt, "metadata CAS attempt")
    max_attempts = _require_positive_integer(max_attempts, "metadata CAS maximum attempts")
    if attempt > max_attempts:
        raise ValueError("metadata CAS attempt exceeds maximum")

    if not isinstance(porcelain_status, str):
        return {"action": "fail", "reason": "push-output-not-text"}

    lines = [raw_line.rstrip("\r") for raw_line in porcelain_status.splitlines()]
    if not lines or any(not line for line in lines):
        return {"action": "fail", "reason": "blank-or-empty-push-output"}

    header_remote = None
    status_row = None
    footer_seen = False
    diagnostics = []
    for line in lines:
        if header_remote is None:
            if not line.startswith("To ") or len(line) <= 3 or "\t" in line:
                return {"action": "fail", "reason": "push-header-order"}
            header_remote = line[3:]
            continue
        if status_row is None:
            if line == "Done" or line.startswith("To "):
                return {"action": "fail", "reason": "push-status-order"}
            fields = line.split("\t")
            if len(fields) != 3 or len(fields[0]) != 1 or ":" not in fields[1]:
                return {"action": "fail", "reason": "unrecognized-push-output"}
            flag, refspec, summary = fields
            if flag not in {" ", "=", "*", "!"}:
                return {"action": "fail", "reason": "unknown-push-status"}
            source, destination = refspec.split(":", 1)
            if not source or not destination:
                return {"action": "fail", "reason": "malformed-push-ref-status"}
            if destination != "refs/heads/patched":
                return {"action": "fail", "reason": "push-ref-status-target-mismatch"}
            allowed_summary = {
                "=": {"[up to date]"},
                "*": {"[new branch]"},
                "!": {
                    "[rejected] (non-fast-forward)",
                    "[rejected] (fetch first)",
                },
            }
            if flag == " " and not re.fullmatch(r"[0-9a-f]{40}\.\.[0-9a-f]{40}", summary):
                return {"action": "fail", "reason": "unknown-push-summary"}
            if flag != " " and summary not in allowed_summary[flag]:
                return {"action": "fail", "reason": "unknown-push-summary"}
            status_row = (flag, destination, summary)
            continue
        if not footer_seen:
            if line != "Done":
                return {"action": "fail", "reason": "push-footer-order"}
            footer_seen = True
            continue

        if line.startswith("error: failed to push some refs to "):
            expected_error = f"error: failed to push some refs to '{header_remote}'"
            if line != expected_error or any(item.startswith("error: ") for item in diagnostics):
                return {"action": "fail", "reason": "unrecognized-push-diagnostic"}
            diagnostics.append(line)
            continue
        if line in NFF_HINTS:
            if line in diagnostics:
                return {"action": "fail", "reason": "duplicate-push-diagnostic"}
            diagnostics.append(line)
            continue
        return {"action": "fail", "reason": "unrecognized-push-diagnostic"}

    if status_row is None or not footer_seen:
        return {"action": "fail", "reason": "push-ref-status-or-footer-missing"}
    flag, destination, summary = status_row
    nff_rejected = flag == "!" and summary in {
        "[rejected] (non-fast-forward)",
        "[rejected] (fetch first)",
    }
    if diagnostics and not nff_rejected:
        return {"action": "fail", "reason": "diagnostic-without-nff"}
    confirmed_nff = (
        push_status != 0
        and nff_rejected
        and remote_head_after != remote_head_before
    )
    if confirmed_nff and not diagnostics:
        # A porcelain NFF row is sufficient; Git may omit stderr diagnostics.
        return {
            "action": "retry" if attempt < max_attempts else "retry-exhausted",
            "reason": "fresh-remote-head-changed",
        }
    if confirmed_nff and diagnostics:
        return {
            "action": "retry" if attempt < max_attempts else "retry-exhausted",
            "reason": "fresh-remote-head-changed",
        }
    if (
        push_status == 0
        and flag in {" ", "=", "*"}
        and not diagnostics
        and (
            (flag == "=" and summary == "[up to date]")
            or (flag == " " and re.fullmatch(r"[0-9a-f]{40}\.\.[0-9a-f]{40}", summary))
            or (flag == "*" and summary == "[new branch]")
        )
    ):
        return {"action": "success", "reason": "push-ok"}
    if nff_rejected and remote_head_after == remote_head_before:
        return {"action": "fail", "reason": "remote-head-unchanged"}
    return {"action": "fail", "reason": "push-failure-not-confirmed-nff"}


def persisted_verified_release_entry(metadata_bytes, expected_entry):
    """Select the persisted entry while allowing only a new runAttempt."""
    try:
        ledger = strict_json_loads(metadata_bytes)
        _validate_ledger(ledger)
        expected = _validate_verified_release_entry(expected_entry)
    except (TypeError, ValueError):
        return {"verified": False, "reason": "invalid-ledger"}
    matches = [
        entry for entry in ledger
        if all(entry[field] == expected[field] for field in VERIFIED_RELEASE_STABLE_FIELDS)
    ]
    if len(matches) != 1:
        return {"verified": False, "reason": "entry-mismatch"}
    return {"verified": True, "reason": "", "entry": matches[0]}


def classify_release_read(exit_status, http_status):
    """Classify a Release/tag GET without treating errors as absence."""
    if (
        isinstance(exit_status, int)
        and not isinstance(exit_status, bool)
        and isinstance(http_status, int)
        and not isinstance(http_status, bool)
    ):
        if exit_status == 0 and http_status == 200:
            return {"action": "present", "reason": "ok"}
        if exit_status != 0 and http_status == 404:
            return {"action": "missing", "reason": "not-found"}
    return {"action": "fail", "reason": "release-read-failed"}


def verify_verified_releases(metadata_bytes, expected_entry):
    """Verify that remote ledger bytes contain exactly one canonical entry."""
    try:
        ledger = strict_json_loads(metadata_bytes)
        _validate_ledger(ledger)
        expected = _validate_verified_release_entry(expected_entry)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return {"verified": False, "reason": "invalid-ledger"}
    matches = [entry for entry in ledger if entry == expected]
    if len(matches) != 1:
        return {"verified": False, "reason": "entry-mismatch"}
    return {"verified": True, "reason": ""}


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
        payload = parse_update_metadata(metadata_bytes)
    except (TypeError, ValueError):
        return {"verified": False, "reason": "invalid-json"}
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
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError("update version must be a 4-part numeric version")
    if not isinstance(apk_url, str) or not apk_url.startswith("https://"):
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

    verified_releases = subparsers.add_parser("reconcile-verified-releases")
    verified_releases.add_argument("--ledger", required=True)
    verified_releases.add_argument("--entry", required=True)
    verified_releases.add_argument("--output", required=True)

    metadata_preflight = subparsers.add_parser("reconcile-verified-release-metadata")
    metadata_preflight.add_argument("--current-update", required=True)
    metadata_preflight.add_argument("--current-ledger", required=True)
    metadata_preflight.add_argument("--candidate-update", required=True)
    metadata_preflight.add_argument("--entry", required=True)
    metadata_preflight.add_argument("--output", required=True)

    parse_update = subparsers.add_parser("parse-update-metadata")
    parse_update.add_argument("--metadata-file", required=True)

    push = subparsers.add_parser("classify-metadata-push")
    push.add_argument("--status", required=True, type=int)
    push.add_argument("--porcelain-file", required=True)
    push.add_argument("--local-parent", required=True)
    push.add_argument("--remote-before", required=True)
    push.add_argument("--remote-after", required=True)
    push.add_argument("--attempt", required=True, type=int)
    push.add_argument("--max-attempts", required=True, type=int)

    release_read = subparsers.add_parser("classify-release-read")
    release_read.add_argument("--status", required=True, type=int)
    release_read.add_argument("--http-status", required=True, type=int)

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
        draft = strict_json_loads(args.draft)
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
        release = strict_json_loads(args.release)
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
    elif args.command == "reconcile-verified-releases":
        result = reconcile_verified_releases(
            strict_json_loads(Path(args.ledger).read_text()),
            strict_json_loads(Path(args.entry).read_text()),
        )
        Path(args.output).write_text(json.dumps(result["ledger"], indent=2) + "\n")
        print(json.dumps({"action": result["action"]}, sort_keys=True))
    elif args.command == "reconcile-verified-release-metadata":
        result = reconcile_verified_release_metadata(
            Path(args.current_update).read_bytes(),
            Path(args.current_ledger).read_bytes(),
            Path(args.candidate_update).read_bytes(),
            strict_json_loads(Path(args.entry).read_text()),
        )
        Path(args.output).write_text(json.dumps(result["ledger"], indent=2) + "\n")
        print(json.dumps({"action": result["action"]}, sort_keys=True))
    elif args.command == "parse-update-metadata":
        print(json.dumps(parse_update_metadata(Path(args.metadata_file).read_bytes()), sort_keys=True))
    elif args.command == "classify-metadata-push":
        result = classify_metadata_push(
            args.status,
            Path(args.porcelain_file).read_text(),
            args.local_parent,
            args.remote_before,
            args.remote_after,
            args.attempt,
            args.max_attempts,
        )
        print(json.dumps(result, sort_keys=True))
    elif args.command == "classify-release-read":
        print(json.dumps(classify_release_read(args.status, args.http_status), sort_keys=True))
    elif args.command == "released-identity":
        release = strict_json_loads(args.release)
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
