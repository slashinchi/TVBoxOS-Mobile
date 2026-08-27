#!/usr/bin/env bash
set -euo pipefail

: "${BUILDER_ROLE:?BUILDER_ROLE is required}"
: "${RELEASE_SHA:?RELEASE_SHA is required}"
: "${SOURCE_SHA:?SOURCE_SHA is required}"
: "${MODE:?MODE is required}"
: "${CONTROL_WORKFLOW_ROOT:?CONTROL_WORKFLOW_ROOT is required}"
: "${WORKFLOW_SOURCE_SHA:?WORKFLOW_SOURCE_SHA is required}"

case "$BUILDER_ROLE" in
  primary|repro) ;;
  *) echo "::error::unsupported builder role: $BUILDER_ROLE"; exit 1 ;;
esac

repo_root="${GITHUB_WORKSPACE:-$PWD}"
cd "$repo_root"
export GRADLE_USER_HOME="$RUNNER_TEMP/tvbox-gradle"
hash_file() { sha256sum "$1" | awk '{print $1}'; }
phase="${U2_BUILDER_PHASE:-pre-build}"
case "$phase" in
  pre-build|post-build) ;;
  *) echo "::error::unsupported builder phase: $phase"; exit 1 ;;
esac
reexec="${U2_BUILDER_REEXEC:-0}"
trusted_control_root="$RUNNER_TEMP/tvbox-control/$BUILDER_ROLE"
post_build_root="$RUNNER_TEMP/tvbox-control/$BUILDER_ROLE-post-build"
case "$reexec" in
  0) [[ "$phase" == "pre-build" ]] || { echo "::error::invalid initial builder phase"; exit 1; } ;;
  1) [[ "$phase" == "pre-build" && "$CONTROL_WORKFLOW_ROOT" == "$trusted_control_root" ]] || { echo "::error::invalid pre-build re-exec binding"; exit 1; } ;;
  2) [[ "$phase" == "post-build" && "$CONTROL_WORKFLOW_ROOT" == "$post_build_root" ]] || { echo "::error::invalid post-build re-exec binding"; exit 1; } ;;
  *) echo "::error::unsupported builder re-exec"; exit 1 ;;
esac
control_source_root="$CONTROL_WORKFLOW_ROOT"
control_source_scripts="$control_source_root/scripts"
if [[ "$reexec" == "0" ]]; then
  rm -rf "$trusted_control_root"
  mkdir -p "$trusted_control_root/scripts"
  for helper in u2_build_evidence.sh legacy_staging.py u2_release.py native_compat.py; do
    test -f "$control_source_scripts/$helper" || {
      echo "::error::missing trusted control helper: $helper"
      exit 1
    }
    cp -- "$control_source_scripts/$helper" "$trusted_control_root/scripts/$helper"
    test "$(hash_file "$control_source_scripts/$helper")" = "$(hash_file "$trusted_control_root/scripts/$helper")" || {
      echo "::error::trusted control helper copy mismatch: $helper"
      exit 1
    }
  done
  trusted_recipe_sha=$(hash_file "$trusted_control_root/scripts/u2_build_evidence.sh")
  trusted_legacy_staging_sha=$(hash_file "$trusted_control_root/scripts/legacy_staging.py")
  trusted_u2_release_sha=$(hash_file "$trusted_control_root/scripts/u2_release.py")
  trusted_native_compat_sha=$(hash_file "$trusted_control_root/scripts/native_compat.py")
  trusted_recipe_b64=$(base64 -w 0 "$trusted_control_root/scripts/u2_build_evidence.sh")
  trusted_legacy_staging_b64=$(base64 -w 0 "$trusted_control_root/scripts/legacy_staging.py")
  trusted_u2_release_b64=$(base64 -w 0 "$trusted_control_root/scripts/u2_release.py")
  trusted_native_compat_b64=$(base64 -w 0 "$trusted_control_root/scripts/native_compat.py")
  exec env \
    U2_BUILDER_REEXEC=1 \
    U2_BUILDER_PHASE=pre-build \
    CONTROL_WORKFLOW_ROOT="$trusted_control_root" \
    U2_TRUSTED_RECIPE_SHA="$trusted_recipe_sha" \
    U2_TRUSTED_LEGACY_STAGING_SHA="$trusted_legacy_staging_sha" \
    U2_TRUSTED_U2_RELEASE_SHA="$trusted_u2_release_sha" \
    U2_TRUSTED_NATIVE_COMPAT_SHA="$trusted_native_compat_sha" \
    U2_TRUSTED_RECIPE_B64="$trusted_recipe_b64" \
    U2_TRUSTED_LEGACY_STAGING_B64="$trusted_legacy_staging_b64" \
    U2_TRUSTED_U2_RELEASE_B64="$trusted_u2_release_b64" \
    U2_TRUSTED_NATIVE_COMPAT_B64="$trusted_native_compat_b64" \
    bash "$trusted_control_root/scripts/u2_build_evidence.sh" "$@"
fi

control_scripts="$CONTROL_WORKFLOW_ROOT/scripts"
for helper in legacy_staging.py u2_release.py native_compat.py; do
  test -f "$control_scripts/$helper" || {
    echo "::error::missing trusted control helper: $helper"
    exit 1
  }
done
trusted_recipe_sha=$(hash_file "$control_scripts/u2_build_evidence.sh")
trusted_legacy_staging_sha=$(hash_file "$control_scripts/legacy_staging.py")
trusted_u2_release_sha=$(hash_file "$control_scripts/u2_release.py")
trusted_native_compat_sha=$(hash_file "$control_scripts/native_compat.py")
verify_trusted_helpers() {
  test "$(hash_file "$control_scripts/u2_build_evidence.sh")" = "$trusted_recipe_sha"
  test "$(hash_file "$control_scripts/legacy_staging.py")" = "$trusted_legacy_staging_sha"
  test "$(hash_file "$control_scripts/u2_release.py")" = "$trusted_u2_release_sha"
  test "$(hash_file "$control_scripts/native_compat.py")" = "$trusted_native_compat_sha"
}
if [[ "$phase" == "post-build" ]]; then
  for expected in \
    "$U2_TRUSTED_RECIPE_SHA" \
    "$U2_TRUSTED_LEGACY_STAGING_SHA" \
    "$U2_TRUSTED_U2_RELEASE_SHA" \
    "$U2_TRUSTED_NATIVE_COMPAT_SHA"; do
    [[ "$expected" =~ ^[0-9a-f]{64}$ ]] || { echo "::error::invalid trusted helper digest"; exit 1; }
  done
  [[ "$trusted_recipe_sha" == "$U2_TRUSTED_RECIPE_SHA" ]] || { echo "::error::post-build recipe digest mismatch"; exit 1; }
  [[ "$trusted_legacy_staging_sha" == "$U2_TRUSTED_LEGACY_STAGING_SHA" ]] || { echo "::error::post-build legacy helper digest mismatch"; exit 1; }
  [[ "$trusted_u2_release_sha" == "$U2_TRUSTED_U2_RELEASE_SHA" ]] || { echo "::error::post-build release helper digest mismatch"; exit 1; }
  [[ "$trusted_native_compat_sha" == "$U2_TRUSTED_NATIVE_COMPAT_SHA" ]] || { echo "::error::post-build native helper digest mismatch"; exit 1; }
fi
trusted_recipe_b64=$(base64 -w 0 "$control_scripts/u2_build_evidence.sh")
trusted_legacy_staging_b64=$(base64 -w 0 "$control_scripts/legacy_staging.py")
trusted_u2_release_b64=$(base64 -w 0 "$control_scripts/u2_release.py")
trusted_native_compat_b64=$(base64 -w 0 "$control_scripts/native_compat.py")
export U2_TRUSTED_RECIPE_SHA="$trusted_recipe_sha"
export U2_TRUSTED_LEGACY_STAGING_SHA="$trusted_legacy_staging_sha"
export U2_TRUSTED_U2_RELEASE_SHA="$trusted_u2_release_sha"
export U2_TRUSTED_NATIVE_COMPAT_SHA="$trusted_native_compat_sha"
export U2_TRUSTED_RECIPE_B64="$trusted_recipe_b64"
export U2_TRUSTED_LEGACY_STAGING_B64="$trusted_legacy_staging_b64"
export U2_TRUSTED_U2_RELEASE_B64="$trusted_u2_release_b64"
export U2_TRUSTED_NATIVE_COMPAT_B64="$trusted_native_compat_b64"

stage_post_build_helpers() {
  rm -rf "$post_build_root"
  mkdir -p "$post_build_root/scripts"
  printf '%s' "$U2_TRUSTED_RECIPE_B64" | base64 --decode > "$post_build_root/scripts/u2_build_evidence.sh"
  printf '%s' "$U2_TRUSTED_LEGACY_STAGING_B64" | base64 --decode > "$post_build_root/scripts/legacy_staging.py"
  printf '%s' "$U2_TRUSTED_U2_RELEASE_B64" | base64 --decode > "$post_build_root/scripts/u2_release.py"
  printf '%s' "$U2_TRUSTED_NATIVE_COMPAT_B64" | base64 --decode > "$post_build_root/scripts/native_compat.py"
  chmod -R a-w "$post_build_root"
  [[ "$(hash_file "$post_build_root/scripts/u2_build_evidence.sh")" == "$U2_TRUSTED_RECIPE_SHA" ]] || { echo "::error::staged recipe digest mismatch"; exit 1; }
  [[ "$(hash_file "$post_build_root/scripts/legacy_staging.py")" == "$U2_TRUSTED_LEGACY_STAGING_SHA" ]] || { echo "::error::staged legacy helper digest mismatch"; exit 1; }
  [[ "$(hash_file "$post_build_root/scripts/u2_release.py")" == "$U2_TRUSTED_U2_RELEASE_SHA" ]] || { echo "::error::staged release helper digest mismatch"; exit 1; }
  [[ "$(hash_file "$post_build_root/scripts/native_compat.py")" == "$U2_TRUSTED_NATIVE_COMPAT_SHA" ]] || { echo "::error::staged native helper digest mismatch"; exit 1; }
  exec env \
    U2_BUILDER_REEXEC=2 \
    U2_BUILDER_PHASE=post-build \
    CONTROL_WORKFLOW_ROOT="$post_build_root" \
    bash "$post_build_root/scripts/u2_build_evidence.sh" "$@"
}

run_assemble_and_reexec() {
  local assembled_apks
  ./gradlew :app:assembleRelease --stacktrace --no-daemon
  mapfile -t assembled_apks < <(find app/build/outputs/apk/release -maxdepth 1 -type f -name '*.apk' -print)
  [[ "${#assembled_apks[@]}" -eq 1 ]] || { echo "::error::expected exactly one assembled release APK"; exit 1; }
  export U2_STATE_ASSEMBLE_APK_SHA="$(hash_file "${assembled_apks[0]}")"
  stage_post_build_helpers "$@"
}

run_dependencies_and_reexec() {
  local apk_before_dependencies apk_after_dependencies source_apk_before_dependencies source_apk_after_dependencies
  apk_before_dependencies=$(hash_file build/evidence/unsigned/unsigned.apk)
  source_apk_before_dependencies=$(hash_file "$apk")
  ./gradlew :app:dependencies --configuration releaseRuntimeClasspath --no-daemon > build/evidence/unsigned/releaseRuntimeClasspath.txt
  apk_after_dependencies=$(hash_file build/evidence/unsigned/unsigned.apk)
  source_apk_after_dependencies=$(hash_file "$apk")
  [[ "$apk_after_dependencies" == "$apk_before_dependencies" && "$source_apk_after_dependencies" == "$source_apk_before_dependencies" ]] || {
    echo "::error::dependencies task changed the unsigned APK"
    exit 1
  }
  export U2_STATE_RAW_DEPENDENCY_SHA="$(hash_file build/evidence/unsigned/releaseRuntimeClasspath.txt)"
  export U2_SKIP_DEPENDENCIES=1
  stage_post_build_helpers "$@"
}

if [[ "$phase" == "post-build" ]]; then
  : "${U2_STATE_VERSION_NAME:?missing post-build version state}"
  : "${U2_STATE_VERSION_CODE:?missing post-build version state}"
  : "${U2_STATE_ASSEMBLE_APK_SHA:?missing post-build APK state}"
  : "${U2_STATE_UPSTREAM_SHA:?missing post-build upstream state}"
  : "${U2_STATE_UPSTREAM_VERSION:?missing post-build upstream state}"
  : "${U2_STATE_UPSTREAM_CODE:?missing post-build upstream state}"
  : "${U2_STATE_RELEASE_DEBT:?missing post-build debt state}"
  : "${U2_STATE_LEGACY_MANIFEST_SHA:?missing post-build manifest state}"
  : "${U2_STATE_IMAGE_OS:?missing post-build image state}"
  : "${U2_STATE_IMAGE_VERSION:?missing post-build image state}"
  : "${U2_STATE_RUNNER_IMAGE:?missing post-build image state}"
  : "${U2_STATE_JAVA_VERSION:?missing post-build Java state}"
  : "${U2_STATE_JAVA_PATH:?missing post-build Java state}"
  : "${U2_STATE_JAVA_BINARY_SHA:?missing post-build Java state}"
  : "${U2_STATE_GRADLE_VERSION:?missing post-build Gradle state}"
  : "${U2_STATE_GRADLE_DISTRIBUTION_SHA:?missing post-build Gradle state}"
  : "${U2_STATE_WRAPPER_JAR_SHA:?missing post-build Gradle state}"
  : "${U2_STATE_AGP_VERSION:?missing post-build AGP state}"
  : "${U2_STATE_APKSIGNER_PATH:?missing post-build Android tool state}"
  : "${U2_STATE_APKSIGNER_VERSION:?missing post-build Android tool state}"
  : "${U2_STATE_APKSIGNER_SHA:?missing post-build Android tool state}"
  : "${U2_STATE_APKSIGNER_JAR_SHA:?missing post-build Android tool state}"
  : "${U2_STATE_AAPT2_PATH:?missing post-build Android tool state}"
  : "${U2_STATE_AAPT2_VERSION:?missing post-build Android tool state}"
  : "${U2_STATE_AAPT2_SHA:?missing post-build Android tool state}"
  : "${U2_STATE_ZIPALIGN_PATH:?missing post-build Android tool state}"
  : "${U2_STATE_ZIPALIGN_VERSION:?missing post-build Android tool state}"
  : "${U2_STATE_ZIPALIGN_SHA:?missing post-build Android tool state}"
  : "${U2_STATE_NDK_ROOT:?missing post-build Android tool state}"
  : "${U2_STATE_NDK_VERSION:?missing post-build Android tool state}"
  : "${U2_STATE_LLVM_READELF:?missing post-build Android tool state}"
  : "${U2_STATE_LLVM_READELF_VERSION:?missing post-build Android tool state}"
  : "${U2_STATE_LLVM_READELF_SHA:?missing post-build Android tool state}"
  version_name="$U2_STATE_VERSION_NAME"
  version_code="$U2_STATE_VERSION_CODE"
  upstream_sha="$U2_STATE_UPSTREAM_SHA"
  upstream_version="$U2_STATE_UPSTREAM_VERSION"
  upstream_code="$U2_STATE_UPSTREAM_CODE"
  debt="$U2_STATE_RELEASE_DEBT"
  legacy_manifest_sha="$U2_STATE_LEGACY_MANIFEST_SHA"
  image_os="$U2_STATE_IMAGE_OS"
  image_version="$U2_STATE_IMAGE_VERSION"
  runner_image="$U2_STATE_RUNNER_IMAGE"
  java_version="$U2_STATE_JAVA_VERSION"
  java_path="$U2_STATE_JAVA_PATH"
  java_binary_sha="$U2_STATE_JAVA_BINARY_SHA"
  gradle_version="$U2_STATE_GRADLE_VERSION"
  gradle_distribution_sha="$U2_STATE_GRADLE_DISTRIBUTION_SHA"
  wrapper_jar_sha="$U2_STATE_WRAPPER_JAR_SHA"
  agp_version="$U2_STATE_AGP_VERSION"
  apksigner_path="$U2_STATE_APKSIGNER_PATH"
  apksigner_tool_version="$U2_STATE_APKSIGNER_VERSION"
  apksigner_sha="$U2_STATE_APKSIGNER_SHA"
  apksigner_jar_sha="$U2_STATE_APKSIGNER_JAR_SHA"
  aapt2_path="$U2_STATE_AAPT2_PATH"
  aapt2_tool_version="$U2_STATE_AAPT2_VERSION"
  aapt2_sha="$U2_STATE_AAPT2_SHA"
  zipalign_path="$U2_STATE_ZIPALIGN_PATH"
  zipalign_tool_version="$U2_STATE_ZIPALIGN_VERSION"
  zipalign_sha="$U2_STATE_ZIPALIGN_SHA"
  ndk_root="$U2_STATE_NDK_ROOT"
  ndk_version="$U2_STATE_NDK_VERSION"
  llvm_readelf="$U2_STATE_LLVM_READELF"
  llvm_readelf_tool_version="$U2_STATE_LLVM_READELF_VERSION"
  llvm_readelf_sha="$U2_STATE_LLVM_READELF_SHA"
  builder_recipe_sha="$trusted_recipe_sha"
  mkdir -p build/evidence
else
  trusted_recipe_sha="$U2_TRUSTED_RECIPE_SHA"
  trusted_legacy_staging_sha="$U2_TRUSTED_LEGACY_STAGING_SHA"
  trusted_u2_release_sha="$U2_TRUSTED_U2_RELEASE_SHA"
  trusted_native_compat_sha="$U2_TRUSTED_NATIVE_COMPAT_SHA"
fi

write_identity() {
  printf '%s\n' \
    "builder_role=$BUILDER_ROLE" \
    "builder_recipe_sha256=$builder_recipe_sha" \
    "workflow_source_sha=$WORKFLOW_SOURCE_SHA" \
    "artifact_source_sha=$RELEASE_SHA" \
    "source_sha=$SOURCE_SHA" \
    "mode=$MODE" \
    "upstream_sha=$upstream_sha" \
    "upstream_version=$upstream_version" \
    "upstream_code=$upstream_code" \
    "version_name=$version_name" \
    "version_code=$version_code" \
    "release_debt=$debt" \
    "candidate_pr=${INPUT_CANDIDATE_PR:-}" \
    "provenance_marker=${INPUT_PROVENANCE_MARKER:-}" \
    "legacy_manifest_sha256=$legacy_manifest_sha" \
    "runner_image_os=$image_os" \
    "runner_image_version=$image_version" \
    "runner_image=$runner_image" \
    "builder_java_version=$java_version" \
    "java_binary_path=$java_path" \
    "java_binary_sha256=$java_binary_sha" \
    "gradle_version=$gradle_version" \
    "gradle_distribution_sha256=$gradle_distribution_sha" \
    "wrapper_jar_sha256=$wrapper_jar_sha" \
    "agp_version=$agp_version" \
    "apksigner_path=$apksigner_path" \
    "apksigner_version=$apksigner_tool_version" \
    "apksigner_sha256=$apksigner_sha" \
    "apksigner_jar_sha256=$apksigner_jar_sha" \
    "aapt2_path=$aapt2_path" \
    "aapt2_version=$aapt2_tool_version" \
    "aapt2_sha256=$aapt2_sha" \
    "zipalign_path=$zipalign_path" \
    "zipalign_version=$zipalign_tool_version" \
    "zipalign_sha256=$zipalign_sha" \
    "ndk_path=$ndk_root" \
    "ndk_version=$ndk_version" \
    "llvm_readelf_version=$llvm_readelf_tool_version" \
    "llvm_readelf_sha256=$llvm_readelf_sha" > build/evidence/build-identity.txt

  jq -n \
    --arg builder_role "$BUILDER_ROLE" \
    --arg builder_recipe_sha256 "$builder_recipe_sha" \
    --arg workflow_source_sha "$WORKFLOW_SOURCE_SHA" \
    --arg artifact_source_sha "$RELEASE_SHA" \
    --arg source_sha "$SOURCE_SHA" \
    --arg mode "$MODE" \
    --arg upstream_sha "$upstream_sha" \
    --arg upstream_version "$upstream_version" \
    --arg upstream_code "$upstream_code" \
    --arg version_name "$version_name" \
    --arg version_code "$version_code" \
    --arg release_debt "$debt" \
    --arg candidate_pr "${INPUT_CANDIDATE_PR:-}" \
    --arg provenance_marker "${INPUT_PROVENANCE_MARKER:-}" \
    --arg legacy_manifest_sha256 "$legacy_manifest_sha" \
    --arg runner_image_os "$image_os" \
    --arg runner_image_version "$image_version" \
    --arg runner_image "$runner_image" \
    --arg builder_java_version "$java_version" \
    --arg java_binary_path "$java_path" \
    --arg java_binary_sha256 "$java_binary_sha" \
    --arg gradle_version "$gradle_version" \
    --arg gradle_distribution_sha256 "$gradle_distribution_sha" \
    --arg wrapper_jar_sha256 "$wrapper_jar_sha" \
    --arg agp_version "$agp_version" \
    --arg apksigner_path "$apksigner_path" \
    --arg apksigner_version "$apksigner_tool_version" \
    --arg apksigner_sha256 "$apksigner_sha" \
    --arg apksigner_jar_sha256 "$apksigner_jar_sha" \
    --arg aapt2_path "$aapt2_path" \
    --arg aapt2_version "$aapt2_tool_version" \
    --arg aapt2_sha256 "$aapt2_sha" \
    --arg zipalign_path "$zipalign_path" \
    --arg zipalign_version "$zipalign_tool_version" \
    --arg zipalign_sha256 "$zipalign_sha" \
    --arg ndk_path "$ndk_root" \
    --arg ndk_version "$ndk_version" \
    --arg llvm_readelf_version "$llvm_readelf_tool_version" \
    --arg llvm_readelf_sha256 "$llvm_readelf_sha" \
    '{schema:"tvbox-release-identity-v2", builder_role:$builder_role, builder_recipe_sha256:$builder_recipe_sha256, workflow_source_sha:$workflow_source_sha, artifact_source_sha:$artifact_source_sha, source_sha:$source_sha, mode:$mode, upstream_sha:$upstream_sha, upstream_version:$upstream_version, upstream_code:($upstream_code|tonumber), version_name:$version_name, version_code:$version_code, release_debt:$release_debt, candidate_pr:$candidate_pr, provenance_marker:$provenance_marker, legacy_manifest_sha256:$legacy_manifest_sha256, runner_image_os:$runner_image_os, runner_image_version:$runner_image_version, runner_image:$runner_image, builder_java_version:$builder_java_version, java_binary_path:$java_binary_path, java_binary_sha256:$java_binary_sha256, gradle_version:$gradle_version, gradle_distribution_sha256:$gradle_distribution_sha256, wrapper_jar_sha256:$wrapper_jar_sha256, agp_version:$agp_version, apksigner_path:$apksigner_path, apksigner_version:$apksigner_version, apksigner_sha256:$apksigner_sha256, apksigner_jar_sha256:$apksigner_jar_sha256, aapt2_path:$aapt2_path, aapt2_version:$aapt2_version, aapt2_sha256:$aapt2_sha256, zipalign_path:$zipalign_path, zipalign_version:$zipalign_version, zipalign_sha256:$zipalign_sha256, ndk_path:$ndk_path, ndk_version:$ndk_version, llvm_readelf_version:$llvm_readelf_version, llvm_readelf_sha256:$llvm_readelf_sha256}' > build/evidence/build-identity.json
  printf '%s\n' "$RELEASE_SHA" > build/evidence/release-source.txt
  {
    echo "version_name=$version_name"
    echo "version_code=$version_code"
    echo "upstream_sha=$upstream_sha"
    echo "upstream_version=$upstream_version"
    echo "upstream_code=$upstream_code"
    echo "release_debt=$debt"
  } > build/evidence/release-fields.env
}

if [[ "$phase" == "post-build" ]]; then
  write_identity
fi

if [[ "$phase" == "pre-build" ]]; then
legacy_repo="$RUNNER_TEMP/tvbox-legacy-maven"
python3 "$control_scripts/legacy_staging.py" stage \
  --manifest gradle/legacy-dependencies.lock.json \
  --output "$legacy_repo"
python3 "$control_scripts/legacy_staging.py" verify \
  --manifest gradle/legacy-dependencies.lock.json \
  --output "$legacy_repo"
manifest_sha=$(python3 "$control_scripts/legacy_staging.py" manifest-digest \
  --manifest gradle/legacy-dependencies.lock.json | jq -r '.manifest_sha256')
test "$manifest_sha" != "null"
export TVBOX_LEGACY_REPO="$legacy_repo"
export TVBOX_LEGACY_MANIFEST_SHA256="$manifest_sha"

mkdir -p build/evidence
test "$(git rev-parse HEAD)" = "$RELEASE_SHA"
if [[ "$MODE" == "manual-local" ]]; then
  test "$RELEASE_SHA" = "$SOURCE_SHA"
  git fetch --no-tags origin +refs/heads/patched:refs/remotes/origin/patched
  test "$(git rev-parse refs/remotes/origin/patched)" = "$RELEASE_SHA"
else
  parent_sha=$(git rev-list --parents -n 1 HEAD | awk '{print $2}')
  test "$parent_sha" = "$SOURCE_SHA" || {
    echo "::error::automatic mode release/source parent identity mismatch"
    exit 1
  }
fi
case "$MODE" in
  auto-upstream|manual-local) ;;
  *) echo "::error::unsupported mode"; exit 1 ;;
esac

version_json=$(python3 "$control_scripts/u2_release.py" parse-app-version --file app/build.gradle)
version_name=$(jq -r '.versionName' <<<"$version_json")
version_code=$(jq -r '.versionCode' <<<"$version_json")
if [[ -n "${INPUT_VERSION_NAME:-}" && "$version_name" != "$INPUT_VERSION_NAME" ]]; then
  echo "::error::release versionName mismatch"
  exit 1
fi
if [[ -n "${INPUT_VERSION_CODE:-}" && "$version_code" != "$INPUT_VERSION_CODE" ]]; then
  echo "::error::release versionCode mismatch"
  exit 1
fi

git fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main
upstream_sha="${INPUT_UPSTREAM_SHA:-}"
upstream_version="${INPUT_UPSTREAM_VERSION:-}"
upstream_code="${INPUT_UPSTREAM_CODE:-}"
if [[ "$MODE" == "manual-local" && -z "$upstream_sha" ]]; then
  upstream_sha=$(git merge-base "$RELEASE_SHA" refs/remotes/origin/main)
  upstream_file="$RUNNER_TEMP/integrated-upstream-build.gradle"
  git show "$upstream_sha:app/build.gradle" > "$upstream_file"
  upstream_json=$(python3 "$control_scripts/u2_release.py" parse-app-version --file "$upstream_file")
  upstream_version=$(jq -r '.versionName' <<<"$upstream_json")
  upstream_code=$(jq -r '.versionCode' <<<"$upstream_json")
fi
if [[ "$MODE" == "auto-upstream" ]]; then
  [[ -n "$upstream_sha" && -n "$upstream_version" && -n "$upstream_code" ]] || {
    echo "::error::automatic mode requires integrated upstream identity"
    exit 1
  }
  [[ -n "${INPUT_PROVENANCE_MARKER:-}" ]] || {
    echo "::error::automatic mode requires v2 provenance"
    exit 1
  }
  marker_json=$(python3 "$control_scripts/u2_release.py" parse-provenance-marker --marker "$INPUT_PROVENANCE_MARKER")
  [[ "$(jq -r '.upstream' <<<"$marker_json")" == "$upstream_sha" ]] || { echo "::error::provenance upstream mismatch"; exit 1; }
  [[ "$(jq -r '.upstreamVersion' <<<"$marker_json")" == "$upstream_version" ]] || { echo "::error::provenance version mismatch"; exit 1; }
  [[ "$(jq -r '.upstreamCode' <<<"$marker_json")" == "$upstream_code" ]] || { echo "::error::provenance code mismatch"; exit 1; }
  candidate_sha=$(jq -r '.candidate' <<<"$marker_json")
  candidate_tree=$(jq -r '.tree' <<<"$marker_json")
  git merge-base --is-ancestor "$candidate_sha" "$SOURCE_SHA"
  test "$(git rev-parse "$candidate_sha^{tree}")" = "$candidate_tree"
else
  test -z "${INPUT_PROVENANCE_MARKER:-}"
fi
python3 - "$upstream_sha" "$upstream_version" "$upstream_code" <<'PY'
import re
import sys

if not re.fullmatch(r"[0-9a-f]{40}", sys.argv[1]):
    raise SystemExit("invalid upstream SHA")
if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", sys.argv[2]):
    raise SystemExit("invalid upstream version")
if not re.fullmatch(r"[1-9][0-9]*", sys.argv[3]):
    raise SystemExit("invalid upstream code")
PY

debt="${INPUT_RELEASE_DEBT:-}"
if [[ -z "$debt" ]]; then
  baseline_tag=$(git tag --list 'v*' --sort=-version:refname | head -n 1)
  [[ -n "$baseline_tag" ]] || { echo "::error::manual mode requires a canonical release baseline"; exit 1; }
  exclusions=(
    '.github/workflows/' 'AGENTS.md' 'README.md' 'docs/' 'update.json'
    'scripts/upstream_monitor.py' 'scripts/tests/' 'scripts/u2_release.py'
    'scripts/sync_release_metadata.sh' 'CHANGELOG.md' 'LICENSE.md' 'NOTICE.md'
  )
  manifest_args=()
  for exclusion in "${exclusions[@]}"; do manifest_args+=(--exclude "$exclusion"); done
  python3 "$control_scripts/u2_release.py" debt-manifest --repo . --baseline "$baseline_tag" --current "$RELEASE_SHA" "${manifest_args[@]}" > "$RUNNER_TEMP/release-debt.json"
  debt=$(python3 "$control_scripts/u2_release.py" fingerprint-manifest --file "$RUNNER_TEMP/release-debt.json")
fi
[[ "$debt" =~ ^[0-9a-f]{64}$ ]] || { echo "::error::invalid release-debt fingerprint"; exit 1; }

image_os="${ImageOS:-}"
image_version="${ImageVersion:-}"
[[ -n "$image_os" && -n "$image_version" ]] || {
  echo "::error::hosted runner image identity is unavailable"
  exit 1
}
runner_image=$(uname -a)
java_version=$(java -version 2>&1 | tr '\n' ' ')
[[ "$java_version" == *"17.0.20"* ]] || { echo "::error::builder JDK is not Temurin 17.0.20"; exit 1; }
java_path=$(readlink -f "$(command -v java)")
apksigner_path="$ANDROID_HOME/build-tools/34.0.0/apksigner"
aapt2_path="$ANDROID_HOME/build-tools/34.0.0/aapt2"
zipalign_path="$ANDROID_HOME/build-tools/35.0.0/zipalign"
ndk_root="$ANDROID_HOME/ndk/28.2.13676358"
llvm_readelf="$ndk_root/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
for tool in "$apksigner_path" "$aapt2_path" "$zipalign_path" "$llvm_readelf"; do
  test -x "$tool"
done
java_binary_sha=$(hash_file "$java_path")
apksigner_sha=$(hash_file "$apksigner_path")
apksigner_jar_sha=$(hash_file "$ANDROID_HOME/build-tools/34.0.0/lib/apksigner.jar")
aapt2_sha=$(hash_file "$aapt2_path")
zipalign_sha=$(hash_file "$zipalign_path")
llvm_readelf_sha=$(hash_file "$llvm_readelf")
apksigner_tool_version=$({ "$apksigner_path" version 2>&1 || true; } | tr '\n' ' ')
aapt2_tool_version=$({ "$aapt2_path" version 2>&1 || true; } | tr '\n' ' ')
zipalign_tool_version=$({ "$zipalign_path" -h 2>&1 || true; } | tr '\n' ' ')
llvm_readelf_tool_version=$({ "$llvm_readelf" --version 2>&1 || true; } | tr '\n' ' ')
[[ -n "$apksigner_tool_version" && -n "$aapt2_tool_version" && -n "$zipalign_tool_version" && -n "$llvm_readelf_tool_version" ]] || {
  echo "::error::Android tool version identity is unavailable"
  exit 1
}
chmod +x gradlew
gradle_version=$(./gradlew --version | sed -nE 's/^Gradle ([^ ]+).*/\1/p' | head -n 1)
[[ "$gradle_version" == "8.7" ]] || { echo "::error::unexpected Gradle version: $gradle_version"; exit 1; }
gradle_distribution_sha=$(sed -nE 's/^distributionSha256Sum=([0-9a-f]{64})/\1/p' gradle/wrapper/gradle-wrapper.properties)
wrapper_jar_sha=$(hash_file gradle/wrapper/gradle-wrapper.jar)
agp_version=$(sed -nE 's/.*com.android.tools.build:gradle:([^" ]+).*/\1/p' build.gradle | head -n 1)
ndk_version="28.2.13676358"
legacy_manifest_sha="$TVBOX_LEGACY_MANIFEST_SHA256"
[[ "$legacy_manifest_sha" =~ ^[0-9a-f]{64}$ ]] || { echo "::error::legacy manifest digest is unavailable"; exit 1; }
builder_recipe_sha="$trusted_recipe_sha"
write_identity

export TVBOX_KEYSTORE_BASE64=''
export TVBOX_KEY_ALIAS=''
export TVBOX_KEY_PASSWORD=''
export TVBOX_STORE_PASSWORD=''
export U2_STATE_VERSION_NAME="$version_name"
export U2_STATE_VERSION_CODE="$version_code"
export U2_STATE_UPSTREAM_SHA="$upstream_sha"
export U2_STATE_UPSTREAM_VERSION="$upstream_version"
export U2_STATE_UPSTREAM_CODE="$upstream_code"
export U2_STATE_RELEASE_DEBT="$debt"
export U2_STATE_LEGACY_MANIFEST_SHA="$legacy_manifest_sha"
export U2_STATE_IMAGE_OS="$image_os"
export U2_STATE_IMAGE_VERSION="$image_version"
export U2_STATE_RUNNER_IMAGE="$runner_image"
export U2_STATE_JAVA_VERSION="$java_version"
export U2_STATE_JAVA_PATH="$java_path"
export U2_STATE_JAVA_BINARY_SHA="$java_binary_sha"
export U2_STATE_GRADLE_VERSION="$gradle_version"
export U2_STATE_GRADLE_DISTRIBUTION_SHA="$gradle_distribution_sha"
export U2_STATE_WRAPPER_JAR_SHA="$wrapper_jar_sha"
export U2_STATE_AGP_VERSION="$agp_version"
export U2_STATE_APKSIGNER_PATH="$apksigner_path"
export U2_STATE_APKSIGNER_VERSION="$apksigner_tool_version"
export U2_STATE_APKSIGNER_SHA="$apksigner_sha"
export U2_STATE_APKSIGNER_JAR_SHA="$apksigner_jar_sha"
export U2_STATE_AAPT2_PATH="$aapt2_path"
export U2_STATE_AAPT2_VERSION="$aapt2_tool_version"
export U2_STATE_AAPT2_SHA="$aapt2_sha"
export U2_STATE_ZIPALIGN_PATH="$zipalign_path"
export U2_STATE_ZIPALIGN_VERSION="$zipalign_tool_version"
export U2_STATE_ZIPALIGN_SHA="$zipalign_sha"
export U2_STATE_NDK_ROOT="$ndk_root"
export U2_STATE_NDK_VERSION="$ndk_version"
export U2_STATE_LLVM_READELF="$llvm_readelf"
export U2_STATE_LLVM_READELF_VERSION="$llvm_readelf_tool_version"
export U2_STATE_LLVM_READELF_SHA="$llvm_readelf_sha"
run_assemble_and_reexec "$@"
fi
mapfile -t apks < <(find app/build/outputs/apk/release -maxdepth 1 -type f -name '*.apk' -print)
[[ "${#apks[@]}" -eq 1 ]] || { echo "::error::expected exactly one release APK"; exit 1; }
apk="${apks[0]}"
[[ "$(hash_file "$apk")" == "$U2_STATE_ASSEMBLE_APK_SHA" ]] || {
  echo "::error::release APK changed after assemble"
  exit 1
}
mkdir -p build/evidence/unsigned
cp -- "$apk" build/evidence/unsigned/unsigned.apk
if "$apksigner_path" verify build/evidence/unsigned/unsigned.apk; then
  echo "::error::builder produced a signed APK"
  exit 1
fi
"$zipalign_path" -c -P 16 -v 4 build/evidence/unsigned/unsigned.apk
badging=$("$aapt2_path" dump badging build/evidence/unsigned/unsigned.apk)
package_name=$(sed -nE "s/^package: name='([^']+)'.*/\1/p" <<<"$badging" | head -n 1)
apk_code=$(sed -nE "s/^package:.*versionCode='([^']+)'.*/\1/p" <<<"$badging" | head -n 1)
apk_name=$(sed -nE "s/^package:.*versionName='([^']+)'.*/\1/p" <<<"$badging" | head -n 1)
[[ "$package_name" == 'com.github.tvbox.osc' ]] || { echo "::error::package mismatch"; exit 1; }
[[ "$apk_code" == "$(sed -n 's/^version_code=//p' build/evidence/release-fields.env)" ]] || { echo "::error::versionCode mismatch"; exit 1; }
[[ "$apk_name" == "$(sed -n 's/^version_name=//p' build/evidence/release-fields.env)" ]] || { echo "::error::versionName mismatch"; exit 1; }

python3 - build/evidence/unsigned/unsigned.apk <<'PY'
import base64
import hashlib
import json
import pathlib
import sys
import zipfile

apk = pathlib.Path(sys.argv[1])
entries = []
with zipfile.ZipFile(apk) as archive:
    for info in sorted(archive.infolist(), key=lambda item: item.filename.encode()):
        if info.is_dir():
            continue
        data = archive.read(info)
        encoded = base64.b64encode(info.filename.encode('utf-8', 'surrogateescape')).decode('ascii')
        entries.append({"path_b64": encoded, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "method": info.compress_type})
pathlib.Path('build/evidence/unsigned/payload-manifest.json').write_text(json.dumps(entries, sort_keys=True, separators=(',', ':')) + '\n')
PY

# Native compatibility rule: every PT_LOAD p_align >= 0x4000.
native_result=$(python3 "$control_scripts/native_compat.py" \
  --apk build/evidence/unsigned/unsigned.apk \
  --llvm-readelf "$llvm_readelf" \
  --output build/evidence/unsigned/native-compat.json)
native_report_sha=$(jq -r '.report_sha256' <<<"$native_result")
native_status=$(jq -r '.status' <<<"$native_result")
native_incompatible_count=$(jq -r '.incompatible_count' <<<"$native_result")
native_incompatible_paths=$(jq -c '.incompatible_paths' <<<"$native_result")
[[ "$native_report_sha" =~ ^[0-9a-f]{64}$ ]] || { echo "::error::invalid native compatibility report digest"; exit 1; }

if [[ "${U2_SKIP_DEPENDENCIES:-}" == "1" ]]; then
  : "${U2_STATE_RAW_DEPENDENCY_SHA:?missing post-dependencies state}"
  [[ "$(hash_file build/evidence/unsigned/releaseRuntimeClasspath.txt)" == "$U2_STATE_RAW_DEPENDENCY_SHA" ]] || {
    echo "::error::dependency report changed during trusted re-exec"
    exit 1
  }
else
  run_dependencies_and_reexec "$@"
fi
verify_trusted_helpers
python3 "$control_scripts/u2_release.py" canonical-runtime-dependencies \
  --file build/evidence/unsigned/releaseRuntimeClasspath.txt \
  --configuration releaseRuntimeClasspath > build/evidence/unsigned/runtime-components.json
unsigned_sha256=$(hash_file build/evidence/unsigned/unsigned.apk)
payload_sha256=$(hash_file build/evidence/unsigned/payload-manifest.json)
dependency_sha256=$(hash_file build/evidence/unsigned/runtime-components.json)
raw_dependency_sha256=$(hash_file build/evidence/unsigned/releaseRuntimeClasspath.txt)
jq --arg unsigned "$unsigned_sha256" \
  --arg payload "$payload_sha256" \
  --arg dependencies "$dependency_sha256" \
  '. + {unsigned_sha256:$unsigned, payload_manifest_sha256:$payload, runtime_components_sha256:$dependencies}' \
  build/evidence/build-identity.json > build/evidence/build-identity.json.tmp
mv build/evidence/build-identity.json.tmp build/evidence/build-identity.json
jq --arg native_report "$native_report_sha" \
  --arg native_status "$native_status" \
  --arg native_count "$native_incompatible_count" \
  --argjson native_paths "$native_incompatible_paths" \
  '. + {native_compat_report_sha256:$native_report, native_compat_status:$native_status, native_incompatible_count:($native_count|tonumber), native_incompatible_paths:$native_paths}' \
  build/evidence/build-identity.json > build/evidence/build-identity.json.tmp
mv build/evidence/build-identity.json.tmp build/evidence/build-identity.json
printf '%s\n' \
  "unsigned_sha256=$unsigned_sha256" \
  "payload_manifest_sha256=$payload_sha256" \
  "runtime_components_sha256=$dependency_sha256" \
  "raw_dependency_report_sha256=$raw_dependency_sha256" \
  "native_compat_report_sha256=$native_report_sha" \
  "native_compat_status=$native_status" \
  "native_incompatible_count=$native_incompatible_count" \
  "native_incompatible_paths=$native_incompatible_paths" \
  "package=$package_name" \
  "version_name=$apk_name" \
  "version_code=$apk_code" >> build/evidence/build-identity.txt

[[ "$(hash_file gradle/legacy-dependencies.lock.json)" == "$legacy_manifest_sha" ]] || {
  echo "::error::legacy manifest changed during build"
  exit 1
}
cp -- build/evidence/unsigned/unsigned.apk build/evidence/unsigned.apk
cp -- build/evidence/unsigned/payload-manifest.json build/evidence/payload-manifest.json
cp -- build/evidence/unsigned/native-compat.json build/evidence/native-compat.json
cp -- build/evidence/unsigned/runtime-components.json build/evidence/runtime-components.json
cp -- gradle/legacy-dependencies.lock.json build/evidence/legacy-dependencies.lock.json
rm -rf build/evidence/unsigned
find build/evidence -type f ! -name 'unsigned.apk' ! -name 'build-identity.json' ! -name 'payload-manifest.json' ! -name 'native-compat.json' ! -name 'runtime-components.json' ! -name 'legacy-dependencies.lock.json' -delete
test "$(find build/evidence -maxdepth 1 -type f | wc -l | tr -d ' ')" -eq 6 || {
  echo "::error::build evidence must contain exactly 6 files"
  exit 1
}
echo "unsigned_sha256=$unsigned_sha256" >> "$GITHUB_OUTPUT"
