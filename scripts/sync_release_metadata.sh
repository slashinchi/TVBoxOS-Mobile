#!/usr/bin/env bash
set -euo pipefail

skip_version_check=false
if [[ "${1:-}" == "--skip-version-check" ]]; then
  skip_version_check=true
  shift
fi

tag_name="${1:?Usage: sync_release_metadata.sh [--skip-version-check] vX.Y.Z}"
version="${tag_name#v}"
repository="${GITHUB_REPOSITORY:-slashinchi/TVBoxOS-Mobile}"
app_version=$(sed -nE "s/^[[:space:]]*versionName '([^']+)'/\1/p" app/build.gradle)

if [[ "$tag_name" != v* || ! "$version" =~ ^[0-9]+(\.[0-9]+)+$ ]]; then
  echo "Expected a tag in the form vX.Y.Z, got: $tag_name" >&2
  exit 1
fi

if [[ "$skip_version_check" == false && "$app_version" != "$version" ]]; then
  echo "Tag $tag_name does not match app version $app_version" >&2
  exit 1
fi

apk_url="https://gh.xxooo.cf/https://github.com/${repository}/releases/download/${tag_name}/TVBox-Mobile-v${version}.apk"

printf '{\n  "version": "%s",\n  "apk_url": "%s"\n}\n' "$version" "$apk_url" > update.json
