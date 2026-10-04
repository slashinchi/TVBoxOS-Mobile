# Execution Log: 2026-10-04--maintenance-sdk-u1-recovery

Append-only. No future success asserted.

## 2026-10-04 local implementation (pre-commit)

- Worktree: `/Users/msy/Documents/Code/Oneplus/TVBoxOS-Mobile-Fork/TVBoxOS-Mobile/.worktrees/maintenance-sdk-20261004`
- Branch: `maintenance/sdk-u1-recovery-20261004` from verified `origin/patched` `65158965915f0ae4f0b694391eb37a6a11f8f22b`
- Master Drive ID `1wDoQgT9hN8OM4Rf0K2Kv-ZIp439c1m1R` readback: `modifiedTime=2026-10-04T10:47:20.764Z`, `version=44`, Status=AUTHORIZED, Active Authorization=`2026-10-04--maintenance-sdk-u1-recovery`
- Protected old workspace verified before edits: HEAD=`78e64dfd78e074d55c8b4a1a7fcca274d3079185`; tracked binary diff SHA-256=`239742918e75867ac911de46dc0b0f0f84f40c870b249a7f1e14d7b423a7e236`; untracked individual filenames count=`275`. Local name-list SHA-256 of current `git ls-files --others --exclude-standard` newline list=`a90835a8480327aa23a37bf62e75461f39a33c407ca8dc56d67b457ae75b76db` (does not match Batch-recorded `bc47866e649fa4141526df02404aa43dadf7b3f4c42160f0e14b72989dff8164`; count/HEAD/tracked-diff match; names were not read/changed/deleted).
- Modified files:
  - `.github/workflows/build.yml` — `build-apk` / `Set up Android SDK` now `with.packages: platform-tools`; pinned action SHA and API34 install retained.
  - `.github/workflows/upstream-monitor.yml` — `candidate_validation` / `Set up Android SDK for candidate build` now `with.packages: platform-tools`; pinned action SHA and API34 install retained.
  - `AGENTS.md` — Framework Entrypoint→Master→Current Batch / authorization-state terminology only; branch/signing/U1/U2c boundaries preserved.
  - `scripts/tests/test_upstream_monitor.py` — added job/step-bound packages assertions plus local stdlib `_yaml_tree`/`_named_step` helpers.
  - `docs/plans/2026-10-04--maintenance-sdk-u1-recovery.md` — approved Batch plan deterministic local copy (synced from maintenance-readback-v2.md clarifications).
  - `outputs/logs/2026-10-04--maintenance-sdk-u1-recovery.md` — this append-only log.

## 2026-10-04T10:54:11Z positive/negative local verification

- Interpreter: `/Users/msy/.local/share/uv/python/cpython-3.12.11-macos-aarch64-none/bin/python3.12`
- Env: `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=<worktree root>`; no dependency install.
- Positive:
  - `scripts/upstream_monitor.py fixture-test` → exit 0
  - `scripts/tests/test_upstream_monitor.py -v` → 40 tests OK
  - `scripts/tests/test_u2_release.py -v` → 88 tests OK
  - Combined discovery/module run earlier also green after `# v3` comment-tolerant uses assertion fix.
- New tests:
  - `U1aContractTests.test_build_apk_setup_android_packages_platform_tools`
  - `U1aContractTests.test_candidate_validation_setup_android_packages_platform_tools`
- Negative mutants confined to worktree `tmp/mutants` then restored:
  - Remove only `build.yml` packages setting → `test_build_apk_setup_android_packages_platform_tools` fails with `KeyError: 'with'`; sibling candidate test still OK. Exit 1.
  - Restore build, remove only `upstream-monitor.yml` packages setting → `test_candidate_validation_setup_android_packages_platform_tools` fails with `KeyError: 'with'`; sibling build test still OK. Exit 1.
  - Restore both tracked files; SHA256 matches good copies; both new tests OK again.
- `git diff --check` clean for current worktree changes.
- No commit/push/PR/workflow dispatch performed this round.
- Old workspace rechecked after edits: HEAD/5 tracked diffs/55 timeline delta/untracked count unchanged; untracked name-list SHA remains local `a90835a8480327aa23a37bf62e75461f39a33c407ca8dc56d67b457ae75b76db` vs Batch-recorded `bc47866e...`.
- Residual note for main thread: Batch-recorded untracked name-list digest algorithm/source mismatch vs current `git ls-files --others --exclude-standard` newline digest; protected contents were not touched.


## 2026-10-04 main-thread local review

- Directly reviewed both complete workflows, complete changed test file, AGENTS, approved plan and log. Runtime workflow diffs remain exactly the two explicit packages settings; no permission, signing, trigger, action version, API34 install or candidate uploader changes.
- Ruby's actual YAML parser independently parsed both workflows and confirmed exact job/step SDK contracts. Main thread ran both new tests successfully and directly read recorded positive/negative evidence: fixture discovery 194 OK, U1 40 OK, U2 88 OK; removing each SDK setting independently produces exactly its corresponding negative failure.
- Main thread completed the AGENTS alignment with stable Entrypoint/Master IDs and corrected the remaining historical REVIEW_PENDING terminology; all branch/signing boundaries remain unchanged.
- Protected old workspace independently checked using the original algorithm: sort individual names from `git ls-files --others --exclude-standard -z`, join with NUL and no trailing NUL, then SHA-256. Count=275 and digest=bc47866e649fa4141526df02404aa43dadf7b3f4c42160f0e14b72989dff8164 match preflight exactly. The earlier newline digest mismatch was a serialization difference, not workspace drift. Old HEAD and tracked diff digest also match exactly.
- Main thread approves only the six reviewed change/plan/log files for the maintenance commit and PR. New caches/mutants/tmp evidence must not be staged. Normal CI must still supply real SDK/build/artifact evidence before merge; local review does not claim overall completion.
