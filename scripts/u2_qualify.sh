#!/usr/bin/env bash
# U2 release qualification: compute canonical baseline + cumulative release
# debt from the fork-owned verified-releases.json, classify the change, and
# decide whether this run qualifies for RC production.
#
# Outputs (GITHUB_OUTPUT when set, otherwise stdout): source_sha, release_sha,
# mode, expected_version_name, expected_version_code, release_debt,
# baseline_tag, debt_classification, noop, qualified.
#
# Fail-closed: unverified baseline, empty debt, or any inconsistency => noop.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_SHA="${SOURCE_SHA:-}"
MODE="${MODE:-}"
NOOP="${NOOP:-false}"

out() {
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf '%s\n' "$1" >> "$GITHUB_OUTPUT"
  else
    printf '%s\n' "$1"
  fi
}

emit() {
  out "source_sha=$SOURCE_SHA"
  out "release_sha=$SOURCE_SHA"
  out "mode=$MODE"
  out "expected_version_name=${EXPECTED_VERSION_NAME:-}"
  out "expected_version_code=${EXPECTED_VERSION_CODE:-}"
  out "release_debt=$RELEASE_DEBT"
  out "baseline_tag=$BASELINE_TAG"
  out "debt_classification=$CLASSIFICATION"
  out "noop=$NOOP"
  out "qualified=$QUALIFIED"
}

# Derive version from the checked-out app/build.gradle.
if [[ -f "$ROOT/app/build.gradle" ]]; then
  version_json=$(python3 "$ROOT/scripts/u2_release.py" parse-app-version --file "$ROOT/app/build.gradle")
  EXPECTED_VERSION_NAME=$(jq -r '.versionName' <<<"$version_json")
  EXPECTED_VERSION_CODE=$(jq -r '.versionCode' <<<"$version_json")
fi

if [[ -z "$SOURCE_SHA" || -z "$MODE" ]]; then
  echo "::error::u2_qualify requires SOURCE_SHA and MODE" >&2
  exit 1
fi

QUALIFIED=false
NOOP=false
RELEASE_DEBT=""
BASELINE_TAG=""
CLASSIFICATION=""

verified_file="$ROOT/gradle/verified-releases.json"
if [[ ! -f "$verified_file" ]]; then
  echo "::error::verified-releases.json missing; cannot qualify release" >&2
  emit
  exit 1
fi

debt_json=$(python3 "$ROOT/scripts/u2_release.py" release-debt \
  --repo "$ROOT" \
  --releases-file "$verified_file" \
  --current "$SOURCE_SHA" \
  --exclude ".github/" --exclude "scripts/" --exclude "docs/" \
  --exclude "gradle/" --exclude "AGENTS.md" --exclude "README.md" \
  --exclude "update.json" 2>/dev/null) || {
  echo "::error::release-debt computation failed" >&2
  emit
  exit 1
}

BASELINE_TAG=$(jq -r '.baseline.tag' <<<"$debt_json")
RELEASE_DEBT=$(jq -r '.fingerprint' <<<"$debt_json")
CLASSIFICATION=$(jq -r '.classification' <<<"$debt_json")

if [[ -z "$RELEASE_DEBT" || "$RELEASE_DEBT" == "null" ]]; then
  echo "::error::release debt fingerprint is empty" >&2
  emit
  exit 1
fi

case "$CLASSIFICATION" in
  docs-only)
    echo "docs-only change: no release work."
    NOOP=true
    ;;
  *)
    if [[ "$NOOP" == "true" ]]; then
      echo "no-op mode: qualification computed, stopping before build."
    else
      QUALIFIED=true
      echo "qualified: ${CLASSIFICATION} with debt ${RELEASE_DEBT}"
    fi
    ;;
esac

emit
