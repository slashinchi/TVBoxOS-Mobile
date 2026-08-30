#!/usr/bin/env python3
"""Pure, fail-closed release qualification helpers for the U2 pipeline."""

import base64
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)+$")
VERSION_CODE_RE = re.compile(r"^[0-9]+$")
RUN_ID_RE = re.compile(r"^[0-9]+$")
HOLD_RELEASE_TAG_RE = re.compile(r"^v[0-9]+(?:\.[0-9]+){3}$")
APPROVAL_RE = re.compile(
    r"\bTVBOX_RELEASE_APPROVE_V2 "
    r"release=(?P<release>[0-9a-f]{40}) "
    r"debt=(?P<debt>[0-9a-f]{64}) "
    r"version=(?P<version>[0-9]+(?:\.[0-9]+)+) "
    r"apk=(?P<apk>[0-9a-f]{64}) "
    r"run=(?P<run>[0-9]+) "
    r"attempt=(?P<attempt>[0-9]+)\b"
)
PROVENANCE_RE = re.compile(
    r"^<!-- tvbox-upstream-candidate-v2 "
    r"upstream=(?P<upstream>[0-9a-f]{40}) "
    r"candidate=(?P<candidate>[0-9a-f]{40}) "
    r"tree=(?P<tree>[0-9a-f]{40}) "
    r"upstreamVersion=(?P<upstreamVersion>[0-9]+(?:\.[0-9]+)+) "
    r"upstreamCode=(?P<upstreamCode>[0-9]+) -->$"
)

FORK_CONTROL_PREFIXES = (".github/", "scripts/")
FORK_CONTROL_FILES = {
    "AGENTS.md",
    "README.md",
    "update.json",
    "CHANGELOG.md",
    "LICENSE.md",
    "NOTICE.md",
}
DOC_SUFFIXES = (".md", ".markdown", ".txt", ".adoc", ".rst")


def _full_sha(value, label):
    if not FULL_SHA_RE.fullmatch(value or ""):
        raise ValueError(f"{label} must be a full 40-character lowercase SHA")
    return value


def candidate_branch_name(upstream_sha):
    return f"automation/upstream-{_full_sha(upstream_sha, 'upstream SHA')}"


def _version_tuple(value):
    if not VERSION_RE.fullmatch(value or ""):
        raise ValueError(f"invalid numeric dotted version: {value!r}")
    return tuple(int(part) for part in value.split("."))


def parse_app_version(text):
    """Parse exactly one active versionName/versionCode pair from Gradle text."""
    names = re.findall(r"^[ \t]*versionName[ \t]+['\"]([^'\"]+)['\"][ \t]*$", text, re.MULTILINE)
    codes = re.findall(r"^[ \t]*versionCode[ \t]+([0-9]+)[ \t]*$", text, re.MULTILINE)
    if len(names) != 1 or len(codes) != 1:
        raise ValueError("expected exactly one active versionName and versionCode")
    name = names[0]
    if not VERSION_RE.fullmatch(name) or not VERSION_CODE_RE.fullmatch(codes[0]):
        raise ValueError("version fields must be numeric and dotted/positive")
    code = int(codes[0])
    if code <= 0:
        raise ValueError("versionCode must be positive")
    return name, code


def _replace_version_fields(text, name_token, code_token):
    name, code = parse_app_version(text)
    replaced, name_count = re.subn(
        r"(^[ \t]*versionName[ \t]+['\"])[^'\"]+(['\"][ \t]*$)",
        rf"\g<1>{name_token}\g<2>",
        text,
        flags=re.MULTILINE,
    )
    replaced, code_count = re.subn(
        r"(^[ \t]*versionCode[ \t]+)[0-9]+([ \t]*$)",
        rf"\g<1>{code_token}\g<2>",
        replaced,
        flags=re.MULTILINE,
    )
    if name_count != 1 or code_count != 1:
        raise ValueError("version overlay requires exactly one active version pair")
    return replaced, (name, code)


def normalize_version_overlay(base_text, ours_text, theirs_text):
    """Three-way merge Gradle text after neutralizing only the two version values."""
    name_token = "TVBOX_U2_VERSION_NAME_SENTINEL"
    code_token = "TVBOX_U2_VERSION_CODE_SENTINEL"
    base, _ = _replace_version_fields(base_text, name_token, code_token)
    ours, ours_version = _replace_version_fields(ours_text, name_token, code_token)
    theirs, theirs_version = _replace_version_fields(theirs_text, name_token, code_token)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ours_path = root / "ours"
        base_path = root / "base"
        theirs_path = root / "theirs"
        ours_path.write_text(ours)
        base_path.write_text(base)
        theirs_path.write_text(theirs)
        result = subprocess.run(
            ["git", "merge-file", "-p", str(ours_path), str(base_path), str(theirs_path)],
            text=True,
            capture_output=True,
        )
    if result.returncode != 0:
        raise ValueError("normalized version overlay has a non-version conflict")
    merged = result.stdout.replace(name_token, ours_version[0]).replace(code_token, str(ours_version[1]))
    if parse_app_version(merged) != ours_version:
        raise ValueError("version overlay did not restore the patched version exactly")
    return merged, theirs_version


def build_provenance_marker(upstream, candidate, tree, upstream_version, upstream_code):
    _full_sha(upstream, "upstream SHA")
    _full_sha(candidate, "candidate SHA")
    _full_sha(tree, "candidate tree")
    _version_tuple(upstream_version)
    if int(upstream_code) <= 0:
        raise ValueError("upstreamCode must be positive")
    return (
        "<!-- tvbox-upstream-candidate-v2 "
        f"upstream={upstream} candidate={candidate} tree={tree} "
        f"upstreamVersion={upstream_version} upstreamCode={int(upstream_code)} -->"
    )


def parse_provenance_marker(marker):
    match = PROVENANCE_RE.fullmatch((marker or "").strip())
    if not match:
        raise ValueError("invalid v2 upstream provenance marker")
    return match.groupdict()


def fresh_integration_replay(replayed_status, replayed_tree, actual_tree):
    """Accept only a clean trusted replay whose tree equals the human merge."""
    if replayed_status != "clean":
        return {"qualified": False, "reason": "replay-not-clean"}
    if not FULL_SHA_RE.fullmatch(replayed_tree or "") or replayed_tree != actual_tree:
        return {"qualified": False, "reason": "replay-tree-mismatch"}
    return {"qualified": True, "reason": "replay-match"}


def qualify_u1_merge(
    *,
    before,
    after,
    parents,
    push_actor,
    pr,
    repository,
    upstream_sha,
    marker,
    candidate_tree,
    upstream_is_ancestor,
    replay,
):
    """Strictly qualify the automatic U1 merge ingress without trusting prose."""
    try:
        _full_sha(before, "push before")
        _full_sha(after, "push after")
        _full_sha(upstream_sha, "upstream SHA")
        parsed = parse_provenance_marker(marker)
    except ValueError as exc:
        return {"qualified": False, "reason": str(exc)}
    if len(parents) != 2 or parents[0] != before or parents[1] != parsed["candidate"]:
        return {"qualified": False, "reason": "merge-parent-mismatch"}
    if push_actor != "slashinchi":
        return {"qualified": False, "reason": "push-actor-mismatch"}
    if not isinstance(pr, dict):
        return {"qualified": False, "reason": "missing-associated-pr"}
    if any(
        (
            pr.get("state") != "closed",
            pr.get("merged_at") is None,
            pr.get("base") != "patched",
            pr.get("merged_by") != "slashinchi",
            pr.get("author") != "github-actions[bot]",
            pr.get("head_repository") != repository,
            pr.get("head") != candidate_branch_name(upstream_sha),
            pr.get("head_sha") != parsed["candidate"],
            pr.get("merge_commit_sha") != after,
        )
    ):
        return {"qualified": False, "reason": "associated-pr-mismatch"}
    if parsed["upstream"] != upstream_sha or parsed["tree"] != candidate_tree:
        return {"qualified": False, "reason": "provenance-object-mismatch"}
    if not upstream_is_ancestor:
        return {"qualified": False, "reason": "upstream-not-ancestor"}
    replay_result = fresh_integration_replay(*replay)
    if not replay_result["qualified"]:
        return replay_result
    return {
        "qualified": True,
        "reason": "qualified-u1-merge",
        "upstream": parsed["upstream"],
        "candidate": parsed["candidate"],
        "tree": parsed["tree"],
        "pr": pr.get("number"),
    }


def derive_integrated_upstream_sha(merge_bases, upstream_history, current_patched):
    """Derive one canonical upstream merge-base for manual-local mode."""
    candidates = [item for item in merge_bases if item in upstream_history and item in current_patched]
    if len(candidates) != 1:
        raise ValueError("integrated upstream merge-base is ambiguous or unavailable")
    return candidates[0]


def canonical_release_baseline(releases, update_version=None, delivery_hold=False):
    """Select one internally consistent published release, never from tag text alone."""
    valid = []
    for release in releases:
        required = ("tag", "target", "versionName", "versionCode", "assetSha256", "signerSha256")
        if any(not release.get(key) for key in required):
            continue
        if not release.get("verified") or not release.get("tag_ancestor"):
            continue
        if not FULL_SHA_RE.fullmatch(release["target"]):
            continue
        _version_tuple(release["versionName"])
        if (
            int(release["versionCode"]) <= 0
            or not HEX64_RE.fullmatch(release["assetSha256"])
            or not HEX64_RE.fullmatch(release["signerSha256"])
        ):
            continue
        valid.append(release)
    if not valid:
        raise ValueError("no internally consistent formal release")
    valid.sort(key=lambda item: (int(item["versionCode"]), _version_tuple(item["versionName"])), reverse=True)
    best = valid[0]
    ties = [item for item in valid if (int(item["versionCode"]), _version_tuple(item["versionName"])) == (int(best["versionCode"]), _version_tuple(best["versionName"]))]
    if len(ties) != 1:
        raise ValueError("formal release baseline is ambiguous")
    if update_version is not None and _version_tuple(update_version) > _version_tuple(best["versionName"]):
        raise ValueError("update metadata points ahead of the canonical release")
    if update_version is not None and _version_tuple(update_version) < _version_tuple(best["versionName"]) and not delivery_hold:
        raise ValueError("update metadata lags without an explicit delivery hold")
    return best


def cumulative_release_debt(repo, baseline, current, exclusions=()):
    """Return the cumulative release debt and its classification from baseline to source."""
    entries = debt_manifest(repo, baseline, current, exclusions)
    paths = [item["path"] for item in entries]
    return {
        "classification": classify_release_paths(paths),
        "paths": paths,
        "manifest": entries,
        "fingerprint": fingerprint_manifest(entries),
    }


def prep_commit_spec(parent_sha, changed_paths, trailers, version_name, version_code, debt):
    """Validate the version-only disposable release-prep contract."""
    _full_sha(parent_sha, "prep parent")
    if set(changed_paths) != {"app/build.gradle"}:
        raise ValueError("release-prep may change app/build.gradle only")
    parsed = {line.split(": ", 1)[0]: line.split(": ", 1)[1] for line in trailers.splitlines() if ": " in line}
    expected = {
        "TVBox-U2-Source": parent_sha,
        "TVBox-U2-Version": version_name,
        "TVBox-U2-Debt": debt,
    }
    for key, value in expected.items():
        if parsed.get(key) != value:
            raise ValueError(f"release-prep trailer mismatch: {key}")
    if int(version_code) <= 0:
        raise ValueError("release-prep versionCode must be positive")
    return {"parent": parent_sha, "versionName": version_name, "versionCode": int(version_code), "debt": debt}


def reconcile_prep(existing, expected):
    """Reuse a prep only when every durable identity field matches exactly."""
    if existing is None:
        return {"action": "create", "reason": "missing"}
    fields = ("parent", "versionName", "versionCode", "debt", "mode", "upstream")
    if any(existing.get(field) != expected.get(field) for field in fields):
        return {"action": "fail", "reason": "prep-identity-mismatch"}
    return {"action": "reuse", "reason": "exact-match"}


def post_promotion_state(patched_sha, release_sha, release_ancestor, formal_state):
    """Classify recovery after the exact release SHA has crossed the promotion point."""
    if formal_state == "published" and patched_sha == release_sha:
        return "published-at-release"
    if formal_state == "published" and release_ancestor:
        return "published-recovery-forward"
    if formal_state == "pending" and patched_sha != release_sha:
        return "pre-promotion-stale"
    if formal_state == "draft" and (patched_sha == release_sha or release_ancestor):
        return "draft-recovery-continue"
    if formal_state == "draft" and patched_sha != release_sha and not release_ancestor:
        return "draft-stale"
    return "fail-closed"


def classify_release_paths(paths):
    """Classify paths with Gradle/build sensitivity before app runtime rules."""
    normalized = [path.strip("/") for path in paths if path.strip("/")]
    if not normalized:
        return "docs-only"

    def classify(path):
        if path.endswith((".gradle", ".gradle.kts")) or path in {
            "settings.gradle",
            "gradle.properties",
            "gradlew",
            "gradlew.bat",
        }:
            return "build/release-sensitive"
        if path.startswith(".github/"):
            return "build/release-sensitive"
        if path.startswith(FORK_CONTROL_PREFIXES) or path in FORK_CONTROL_FILES:
            return "docs-only"
        if path.startswith("docs/") and path.endswith(DOC_SUFFIXES):
            return "docs-only"
        if path.startswith(("app/", "player/")) or path.endswith((".java", ".kt", ".xml")):
            return "runtime/high-risk"
        return "unknown/high-risk"

    classes = {classify(path) for path in normalized}
    if classes == {"docs-only"}:
        return "docs-only"
    if "build/release-sensitive" in classes:
        return "build/release-sensitive"
    if "runtime/high-risk" in classes:
        return "runtime/high-risk"
    return "unknown/high-risk"


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    ).stdout


def _tree_entries(repo, treeish):
    entries = {}
    for record in _git(repo, "ls-tree", "-r", "-z", "--full-tree", treeish).split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        mode, object_type, oid = header.decode("ascii").split()
        entries[path] = {
            "path": path.decode("utf-8", "surrogateescape"),
            "path_b64": base64.b64encode(path).decode("ascii"),
            "mode": mode,
            "type": object_type,
            "oid": oid,
        }
    return entries


def debt_manifest(repo, baseline, current, exclusions=()):
    """Return a sorted binary-safe manifest of release-relevant tree changes."""
    excluded = tuple(item.encode("utf-8") for item in exclusions)
    before = _tree_entries(repo, baseline)
    after = _tree_entries(repo, current)
    manifest = []
    for path in sorted(set(before) | set(after)):
        if any(path == item or path.startswith(item) for item in excluded):
            continue
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        item = dict(new or old)
        item["deleted"] = new is None
        manifest.append(item)
    return manifest


def fingerprint_manifest(manifest):
    payload = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def plan_version(upstream_name, upstream_code, published):
    """Plan the next fork revision without trusting tag text alone."""
    upstream_tuple = _version_tuple(upstream_name)
    published_versions = [(_version_tuple(name), int(code), name) for name, code in published]
    if any(code <= 0 for _, code, _ in published_versions):
        raise ValueError("published versionCode must be positive")
    if published_versions and upstream_tuple < max(item[0] for item in published_versions)[: len(upstream_tuple)]:
        raise ValueError("upstream version regressed below published fork version")
    same_family = [
        item for item in published_versions if item[0][: len(upstream_tuple)] == upstream_tuple
    ]
    revision = max(
        (item[0][-1] if len(item[0]) > len(upstream_tuple) else 0 for item in same_family),
        default=0,
    ) + 1
    if revision > 99:
        raise ValueError("fork revision exceeds two-digit bound")
    code = int(upstream_code) * 100 + revision
    if any(code <= item[1] for item in published_versions):
        raise ValueError("planned versionCode is not monotonic")
    return {"versionName": f"{upstream_name}.{revision}", "versionCode": code, "revision": revision}


def build_release_trailers(source_sha, mode, upstream_sha, version_name, debt, pr_number=None, version_code=None):
    _full_sha(source_sha, "source SHA")
    _full_sha(upstream_sha, "upstream SHA")
    if mode not in {"auto-upstream", "manual-local"}:
        raise ValueError("unsupported release mode")
    _version_tuple(version_name)
    if not HEX64_RE.fullmatch(debt or ""):
        raise ValueError("release debt must be a SHA-256 fingerprint")
    lines = [
        f"TVBox-U2-Source: {source_sha}",
        f"TVBox-U2-Mode: {mode}",
        f"TVBox-U2-Upstream: {upstream_sha}",
        f"TVBox-U2-Version: {version_name}",
        f"TVBox-U2-Debt: {debt}",
    ]
    if version_code is not None:
        lines.append(f"TVBox-U2-Code: {int(version_code)}")
    if pr_number is not None:
        lines.append(f"TVBox-U2-PR: {int(pr_number)}")
    return "\n".join(lines)


def build_approval_marker(release_sha, debt, version, apk_sha, run, attempt):
    """Build the exact binary-bound production approval marker."""
    _full_sha(release_sha, "release SHA")
    if not HEX64_RE.fullmatch(debt or ""):
        raise ValueError("approval debt must be a SHA-256 fingerprint")
    _version_tuple(version)
    if not HEX64_RE.fullmatch(apk_sha or ""):
        raise ValueError("approval APK SHA must be a SHA-256 digest")
    if not RUN_ID_RE.fullmatch(str(run)) or not RUN_ID_RE.fullmatch(str(attempt)):
        raise ValueError("approval run/attempt must be numeric")
    return (
        "TVBOX_RELEASE_APPROVE_V2 "
        f"release={release_sha} debt={debt} version={version} "
        f"apk={apk_sha} run={run} attempt={attempt}"
    )


def parse_approval_marker(marker):
    """Parse and strictly validate an approval marker embedded in text.

    The marker must appear as a standalone token; surrounding prose, markdown
    fences or whitespace are tolerated but every bound field must match exactly.
    """
    match = APPROVAL_RE.search((marker or "").strip())
    if not match:
        raise ValueError("invalid exact release approval marker")
    return match.groupdict()


def approval_matches_release(marker, release):
    """True only when the approval marker binds the exact same release identity."""
    try:
        parsed = parse_approval_marker(marker)
    except ValueError:
        return False
    if not isinstance(release, dict):
        return False
    fields = {
        "release": "release_sha",
        "debt": "debt",
        "version": "version",
        "apk": "apk_sha",
        "run": "run",
        "attempt": "attempt",
    }
    for parsed_key, release_key in fields.items():
        if parsed[parsed_key] != str(release.get(release_key, "")):
            return False
    return True


def hold_covers_lag(hold, release, lag_version):
    """A delivery hold covers a lagging update only when it names the same release."""
    if not isinstance(hold, dict) or not isinstance(release, dict):
        return False
    tag = hold.get("release_tag") or ""
    if not HOLD_RELEASE_TAG_RE.fullmatch(tag):
        raise ValueError("delivery hold must name a formal v* release tag")
    if hold.get("release_target") != release.get("target"):
        return False
    if tag != release.get("tag"):
        return False
    if not isinstance(hold.get("issue"), int) or hold["issue"] <= 0:
        raise ValueError("delivery hold must carry a positive issue number")
    _version_tuple(lag_version)
    return True


def canonical_runtime_dependencies(text, configuration):
    """Normalize Gradle's dependency tree to a stable selected-GAV JSON object."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", configuration or ""):
        raise ValueError("invalid dependency configuration")
    gav_re = re.compile(
        r"(?P<group>[A-Za-z0-9_.-]+):(?P<module>[A-Za-z0-9_.-]+):"
        r"(?P<requested>[A-Za-z0-9][A-Za-z0-9+_.-]*)"
        r"(?:\s*->\s*(?P<selected>[A-Za-z0-9][A-Za-z0-9+_.-]*))?"
    )
    selected = {}
    for line in (text or "").splitlines():
        for match in gav_re.finditer(line):
            group = match.group("group")
            module = match.group("module")
            version = match.group("selected") or match.group("requested")
            key = (group, module)
            is_selected = match.group("selected") is not None
            previous = selected.get(key)
            if previous is None:
                selected[key] = (version, is_selected)
            elif is_selected:
                if previous[1] and previous[0] != version:
                    raise ValueError(f"conflicting selected versions for {group}:{module}")
                selected[key] = (version, True)
            elif previous[1]:
                continue
            elif previous[0] != version:
                raise ValueError(f"conflicting selected versions for {group}:{module}")
    if not selected:
        raise ValueError("dependency report contains no selected external GAVs")
    components = [
        {"group": group, "module": module, "version": version[0]}
        for (group, module), version in sorted(selected.items())
    ]
    return {
        "schema": "tvbox-runtime-dependencies-v1",
        "configuration": configuration,
        "components": components,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    version_parser = subparsers.add_parser("parse-app-version")
    version_parser.add_argument("--file", required=True)

    marker_parser = subparsers.add_parser("provenance-marker")
    marker_parser.add_argument("--upstream", required=True)
    marker_parser.add_argument("--candidate", required=True)
    marker_parser.add_argument("--tree", required=True)
    marker_parser.add_argument("--upstream-version", required=True)
    marker_parser.add_argument("--upstream-code", required=True, type=int)

    parse_marker_parser = subparsers.add_parser("parse-provenance-marker")
    parse_marker_parser.add_argument("--marker", required=True)

    overlay_parser = subparsers.add_parser("normalize-version-overlay")
    overlay_parser.add_argument("--base-file", required=True)
    overlay_parser.add_argument("--ours-file", required=True)
    overlay_parser.add_argument("--theirs-file", required=True)
    overlay_parser.add_argument("--output", required=True)

    classify_parser = subparsers.add_parser("classify-paths")
    classify_parser.add_argument("paths", nargs="+")

    manifest_parser = subparsers.add_parser("debt-manifest")
    manifest_parser.add_argument("--repo", default=".")
    manifest_parser.add_argument("--baseline", required=True)
    manifest_parser.add_argument("--current", required=True)
    manifest_parser.add_argument("--exclude", action="append", default=[])

    fingerprint_parser = subparsers.add_parser("fingerprint-manifest")
    fingerprint_parser.add_argument("--file", required=True)

    version_plan_parser = subparsers.add_parser("plan-version")
    version_plan_parser.add_argument("--upstream-name", required=True)
    version_plan_parser.add_argument("--upstream-code", required=True, type=int)
    version_plan_parser.add_argument("--published-file", required=True)

    trailers_parser = subparsers.add_parser("release-trailers")
    trailers_parser.add_argument("--source", required=True)
    trailers_parser.add_argument("--mode", required=True)
    trailers_parser.add_argument("--upstream", required=True)
    trailers_parser.add_argument("--version", required=True)
    trailers_parser.add_argument("--code", type=int)
    trailers_parser.add_argument("--debt", required=True)
    trailers_parser.add_argument("--pr", type=int)

    dependency_parser = subparsers.add_parser("canonical-runtime-dependencies")
    dependency_parser.add_argument("--file", required=True)
    dependency_parser.add_argument("--configuration", required=True)

    debt_parser = subparsers.add_parser("release-debt")
    debt_parser.add_argument("--repo", default=".")
    debt_parser.add_argument("--releases-file", required=True)
    debt_parser.add_argument("--current", required=True)
    debt_parser.add_argument("--exclude", action="append", default=[])

    baseline_parser = subparsers.add_parser("canonical-release-baseline")
    baseline_parser.add_argument("--file", required=True)

    approval_parser = subparsers.add_parser("approval-matches")
    approval_parser.add_argument("--marker", required=True)
    approval_parser.add_argument("--release-sha", required=True)
    approval_parser.add_argument("--debt", required=True)
    approval_parser.add_argument("--version", required=True)
    approval_parser.add_argument("--apk", required=True)
    approval_parser.add_argument("--run", required=True)
    approval_parser.add_argument("--attempt", required=True)

    qualify_parser = subparsers.add_parser("qualify-u1")
    qualify_parser.add_argument("--before", required=True)
    qualify_parser.add_argument("--after", required=True)
    qualify_parser.add_argument("--parents", nargs="+", required=True)
    qualify_parser.add_argument("--actor", required=True)
    qualify_parser.add_argument("--pr", required=True)
    qualify_parser.add_argument("--repository", required=True)
    qualify_parser.add_argument("--upstream", required=True)
    qualify_parser.add_argument("--marker", required=True)
    qualify_parser.add_argument("--candidate-tree", required=True)
    qualify_parser.add_argument("--upstream-ancestor", required=True, choices=["true", "false"])
    qualify_parser.add_argument("--replay-status", required=True)
    qualify_parser.add_argument("--replay-tree", required=True)
    qualify_parser.add_argument("--replay-actual-tree", required=True)

    plan_prep_parser = subparsers.add_parser("plan-prep")
    plan_prep_parser.add_argument("--upstream-name", required=True)
    plan_prep_parser.add_argument("--upstream-code", required=True, type=int)
    plan_prep_parser.add_argument("--published-file", required=True)
    plan_prep_parser.add_argument("--source", required=True)
    plan_prep_parser.add_argument("--mode", required=True, choices=["auto-upstream", "manual-local"])
    plan_prep_parser.add_argument("--upstream", required=True)
    plan_prep_parser.add_argument("--debt", required=True)
    plan_prep_parser.add_argument("--pr", type=int)

    write_prep_parser = subparsers.add_parser("write-prep-version")
    write_prep_parser.add_argument("--file", required=True)
    write_prep_parser.add_argument("--version-name", required=True)
    write_prep_parser.add_argument("--version-code", required=True)

    args = parser.parse_args(argv)
    if args.command == "parse-app-version":
        print(json.dumps(dict(zip(("versionName", "versionCode"), parse_app_version(Path(args.file).read_text())))))
    elif args.command == "provenance-marker":
        print(build_provenance_marker(args.upstream, args.candidate, args.tree, args.upstream_version, args.upstream_code))
    elif args.command == "parse-provenance-marker":
        print(json.dumps(parse_provenance_marker(args.marker), sort_keys=True))
    elif args.command == "normalize-version-overlay":
        merged, upstream = normalize_version_overlay(
            Path(args.base_file).read_text(),
            Path(args.ours_file).read_text(),
            Path(args.theirs_file).read_text(),
        )
        Path(args.output).write_text(merged)
        print(json.dumps({"upstreamVersion": upstream[0], "upstreamCode": upstream[1]}))
    elif args.command == "classify-paths":
        print(classify_release_paths(args.paths))
    elif args.command == "debt-manifest":
        print(json.dumps(debt_manifest(Path(args.repo), args.baseline, args.current, args.exclude), ensure_ascii=True))
    elif args.command == "fingerprint-manifest":
        print(fingerprint_manifest(json.loads(Path(args.file).read_text())))
    elif args.command == "plan-version":
        print(json.dumps(plan_version(args.upstream_name, args.upstream_code, json.loads(Path(args.published_file).read_text()))))
    elif args.command == "release-trailers":
        print(build_release_trailers(args.source, args.mode, args.upstream, args.version, args.debt, args.pr, args.code))
    elif args.command == "canonical-runtime-dependencies":
        result = canonical_runtime_dependencies(Path(args.file).read_text(), args.configuration)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    elif args.command == "release-debt":
        releases = json.loads(Path(args.releases_file).read_text())
        baseline = canonical_release_baseline(releases)
        debt = cumulative_release_debt(Path(args.repo), baseline["target"], args.current, args.exclude)
        print(json.dumps({
            "baseline": {
                "tag": baseline["tag"],
                "target": baseline["target"],
                "versionName": baseline["versionName"],
                "versionCode": baseline["versionCode"],
            },
            "classification": debt["classification"],
            "fingerprint": debt["fingerprint"],
            "path_count": len(debt["paths"]),
        }, sort_keys=True))
    elif args.command == "canonical-release-baseline":
        baseline = canonical_release_baseline(json.loads(Path(args.file).read_text()))
        print(json.dumps({
            "tag": baseline["tag"],
            "target": baseline["target"],
            "versionName": baseline["versionName"],
            "versionCode": baseline["versionCode"],
        }, sort_keys=True))
    elif args.command == "approval-matches":
        release = {
            "release_sha": args.release_sha,
            "debt": args.debt,
            "version": args.version,
            "apk_sha": args.apk,
            "run": args.run,
            "attempt": args.attempt,
        }
        if approval_matches_release(args.marker, release):
            print(json.dumps({"matched": True}, sort_keys=True))
        else:
            print(json.dumps({"matched": False}, sort_keys=True))
    elif args.command == "qualify-u1":
        pr = json.loads(args.pr)
        replay = (args.replay_status, args.replay_tree, args.replay_actual_tree)
        result = qualify_u1_merge(
            before=args.before,
            after=args.after,
            parents=args.parents,
            push_actor=args.actor,
            pr=pr,
            repository=args.repository,
            upstream_sha=args.upstream,
            marker=args.marker,
            candidate_tree=args.candidate_tree,
            upstream_is_ancestor=(args.upstream_ancestor == "true"),
            replay=replay,
        )
        print(json.dumps(result, sort_keys=True))
    elif args.command == "plan-prep":
        if args.upstream_name:
            planned = plan_version(args.upstream_name, args.upstream_code, json.loads(Path(args.published_file).read_text()))
        else:
            name, code = parse_app_version(Path("app/build.gradle").read_text())
            planned = {"versionName": name, "versionCode": code}
        trailers = build_release_trailers(
            args.source,
            args.mode,
            args.upstream,
            planned["versionName"],
            args.debt,
            pr_number=args.pr,
            version_code=planned["versionCode"],
        )
        spec = prep_commit_spec(
            args.source,
            ["app/build.gradle"],
            trailers,
            planned["versionName"],
            planned["versionCode"],
            args.debt,
        )
        print(json.dumps({
            "versionName": planned["versionName"],
            "versionCode": planned["versionCode"],
            "trailers": trailers,
            "spec": spec,
        }, sort_keys=True))
    elif args.command == "write-prep-version":
        path = Path(args.file)
        replaced, _ = _replace_version_fields(path.read_text(), args.version_name, args.version_code)
        path.write_text(replaced)
        print(json.dumps({"versionName": args.version_name, "versionCode": int(args.version_code)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
