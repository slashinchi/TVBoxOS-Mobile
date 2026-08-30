# U2b Closeout-Adjustment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the U2b release orchestrator on a hardened topology that relies only on documented GitHub behavior, with a disposable flag-false canary proving the full production contract, then return to `REVIEW_PENDING`.

**Architecture:** Replace the dual `release-production` environment jobs (approval + publish) with a single no-environment `rc_summary` job (prints the exact approval marker) followed by exactly one `publish` job that owns `release-production`, verifies the current-run approval marker from review history, revalidates identity/attestation/APK/default-branch/immutable-setting, creates/reconciles a draft (exact-identity missing-only repair, no clobber), verifies both assets by API digest + download bytes before publish, publishes, then verifies immutable/delivery/metadata and reconciles incidents. Remove the persistent `canary_mode`/`TVBOX_CANARY_INJECT`/forced-qualification bypass from the production file; prove the same CLIs via a temporary dispatch-only harness that calls the same `rc-pipeline.yml` and `release-production`.

**Tech Stack:** Python 3.11+ (stdlib only: argparse/json/re/zipfile/hashlib/subprocess/pathlib), Bash, GitHub Actions YAML, `gh` CLI, `gws` for Drive control plane.

## Global Constraints

- `TVBOX_U2_ENABLED=false` throughout U2b; final canary keeps flag false and uses a disposable harness; zero formal side effects (`v*` tag/Release/`update.json` untouched).
- All `.github/workflows/**` changes merge via PR to `patched` (no direct workflow pushes).
- No force push, no `--force-with-lease`; CAS uses normal non-fast-forward-failing `git push`.
- No `--clobber` in production paths; missing-only upload after exact digest verification.
- No new Python dependencies; YAML structure tests may use Ruby's stdlib YAML (available on macOS CI runner) or a small hand-rolled parser — never `_job_block`+`assertIn` alone.
- One `release-production` approval per run; approval binds `TVBOX_RELEASE_APPROVE_V2 release=<full> debt=<sha256> version=<v> apk=<sha256> run=<id> attempt=<n>`.
- All incidents keyed by `mode + source SHA + version + debt fingerprint`; close when conditions satisfied.
- FACTS append-only; HANDOFF holistic rewrite; ACTIVE-PLAN living; DECISIONS append/supersede.
- Keep diffs minimal; do not refactor unrelated code.

---

## Task 1: Control-plane & spec updates (batch A)

**Files:**
- Create: `docs/plans/2026-08-30--u2b-closeout-adjustment.md` (this file)
- Modify: `docs/requirements/2026-08-28--u2-release-orchestrator.md` §3.7 (approval/publish topology)
- Drive: HANDOFF → `NEEDS_REPLAN`; ACTIVE-PLAN mark closeout in progress; FACTS append; DECISIONS append D-038.

- [ ] **Step 1:** Write this plan document.
- [ ] **Step 2:** Update §3.7: single `publish` job owns `release-production`; `rc_summary` no environment; remove approval/publish dual-env; publish concurrency stays job-level but is documented as best-effort (canonical-state recompute is the concurrency authority); `queue: max` optional.
- [ ] **Step 3:** Drive updates per `gws` (HANDOFF `NEEDS_REPLAN`, ACTIVE-PLAN `AUTHORIZED` after user approval, FACTS append evidence, DECISIONS append D-038).
- [ ] **Step 4:** Commit + verify Drive byte readback.

## Task 2: Helper TDD in `scripts/u2_publish.py` + tests (batch B)

**Files:**
- Modify: `scripts/u2_publish.py`
- Modify: `scripts/tests/test_u2_publish.py`

- [ ] **Step 1:** Add `reconcile_draft_decision(draft, version, expected_tag, expected_target_sha, apk_digest, update_digest)` returning `exact-reuse | repair-missing | reject-*` (identity via `isDraft + tagName + tagTargetSha`; never bare `targetCommitish`).
- [ ] **Step 2:** Add `verify_release_assets(release, version, expected_digests, download_dir)` — API digest + downloaded raw SHA + exact bytes for both assets; fail closed on missing/extra/mismatch.
- [ ] **Step 3:** Add `verify_remote_metadata(metadata_bytes, expected_version, expected_apk_url)` byte-exact readback.
- [ ] **Step 4:** Add `verify_apk_identity(apk_path, expected_signer_sha, expected_package, expected_version_name)` (apksigner/aapt2-free pure check where feasible; otherwise wire to available tools with fail-closed).
- [ ] **Step 5:** Add `incident_key(mode, source_sha, version, debt)` + `incident_satisfied(...)` + CLI `incident-open/close`.
- [ ] **Step 6:** Update `reconcile-draft` CLI to require non-empty `--update-digest` (empty → reject), output decision enum, and support `--tag-target-sha`.
- [ ] **Step 7:** Tests: exact reuse; missing APK → repair; missing update → repair; wrong digest → reject; extra asset → reject; not-draft → reject; tag-target mismatch → reject; empty update digest → reject; CLI round-trips; remote byte verification with fake download dir; incident key/dedup/close.
- [ ] **Step 8:** Run `python3 -m unittest scripts.tests.test_u2_publish scripts.tests.test_u2_release -v`; all PASS.

## Task 3: Production workflow rewrite (batch C)

**Files:**
- Modify: `.github/workflows/u2-release.yml`

- [ ] **Step 1:** Add `rc_summary` job (no environment) after `build_rc`: prints full §3.3 evidence + exact `TVBOX_RELEASE_APPROVE_V2` marker to step summary and run log; no secrets.
- [ ] **Step 2:** Delete `approval` job; move marker-verification into `publish` (reads current-run `approvals` API, requires exactly one approved `release-production` review for this run whose comment matches the marker, rejects any non-matching comment all-or-nothing).
- [ ] **Step 3:** Delete `canary_publish` job + `canary_mode` input + `TVBOX_CANARY_INJECT` + forced `qualified=true` in `qualify`; remove `canary` outputs usage; keep gate strict flag=false.
- [ ] **Step 4:** Rewrite `publish` job:
  - verify approval marker from review history;
  - revalidate source/debt/prep/release-SHA/artifact digest/attestation/signer/package/version/default-branch `patched`/immutable-release setting;
  - independent APK re-download + identity check;
  - CAS promote (normal push, fail closed on non-FF);
  - `gh release create --draft --target $RELEASE_SHA` only when tag/draft absent; else `reconcile-draft` with non-empty digests and `repair-missing` uploads (no clobber);
  - API digest + download bytes for both assets before `gh release publish`;
  - post-publish: `gh release verify` + `verify-asset` + tag-object SHA + immutable=true + asset-set; delivery proxy with bounded retries/timeouts/redirects → wrong/unreachable opens identity-bound `release-delivery` incident (no metadata write); monotonic `update.json` via `build-update-json` + commit + remote blob byte readback; close satisfied incidents; delete prep ref.
- [ ] **Step 5:** `watch_approval` uses `rc_summary` identity outputs, keyed by `mode+source+version+debt`, records only explicit `slashinchi/rejected`; operational failures never `human-blocked`.
- [ ] **Step 6:** Run `bash -n`, Ruby/PyYAML parse, `git diff --check`.

## Task 4: Structural tests rewrite (batch D)

**Files:**
- Modify: `scripts/tests/test_u2_release.py`
- Modify: `scripts/tests/test_upstream_monitor.py` (fixture regression)

- [ ] **Step 1:** Replace `_job_block`+`assertIn` workflows with YAML-structure assertions: parse jobs, needs, permissions, environment, concurrency, steps order, helper argv; assert `rc_summary` has no environment, `publish` is sole `release-production`, no `canary_mode`/`TVBOX_CANARY_INJECT`, `queue` semantics documented, release write enumeration, signer consumer enumeration.
- [ ] **Step 2:** Add CLI-level tests for `reconcile-draft` decision enum, `verify-release-assets`, `verify-remote-metadata`, incident CLIs.
- [ ] **Step 3:** Update tests that locked the old behavior (empty update digest allowed; `never auto-repaired`; `canary` substrings; `queue:max` comment-only).
- [ ] **Step 4:** `fixture_tests` checkout gets `fetch-depth: 0` (fix run 33298978150); regression assert.
- [ ] **Step 5:** Run full suite + py_compile + YAML parse + bash -n + diff --check.

## Task 5: PR + remote validation (batch F)

- [ ] **Step 1:** Topic branch `u2b-closeout` → PR → merge to `patched`.
- [ ] **Step 2:** Verify remote CI `build-apk` PASS; U2 gate PASS with release jobs skipped (flag=false); upstream-monitor force-check PASS.
- [ ] **Step 3:** Re-run full local suite on merged HEAD.

## Task 6: Disposable canary harness (batch G)

**Files:**
- Create: `.github/workflows/u2-canary-harness.yml` (dispatch-only, actor `slashinchi`, calls same `rc-pipeline.yml` + `release-production` + same `u2_publish.py` CLIs; no `push` trigger)

- [ ] **Step 1:** Harness matrix: (A) two overlapping runs → both complete pre-approval → approve exactly one → old RC publish attempt fails revalidation (stale), new RC publishes to `u2-canary-*` draft only; (B) exact two-asset draft; (C) missing expected asset → repair (no clobber); (D) extra/wrong digest → reject with no mutation; (E) synthetic delivery timeout/stale/wrong/redirect → incident, no metadata write; (F) shadow `patched/update.json` on a disposable branch; (G) `always()` cleanup → zero `u2-canary-*` refs/drafts/tags/vars; production `patched/update.json` untouched.
- [ ] **Step 2:** Run harness with `TVBOX_U2_ENABLED=false` (flag stays false); verify same CLIs and `rc-pipeline.yml`.
- [ ] **Step 3:** Second PR removes harness file + any residual vars/refs; verify zero residue + full local/remote suite.

## Task 7: Final review & Drive closeout (batch H)

- [ ] **Step 1:** Re-run executor + Grok 4.6 xhigh + Gemini 3.1 Pro high on harness-free HEAD; Claude Opus 4.6 Thinking after agy quota reset (or explicit user waiver).
- [ ] **Step 2:** Fix all P0/P1/P2; re-run suite.
- [ ] **Step 3:** Drive: HANDOFF → `REVIEW_PENDING` (byte-equal readback), FACTS append final evidence, ACTIVE-PLAN closeout complete.
- [ ] **Step 4:** Return `REVIEW_PENDING`; first real Release remains U2c live-observation.

## Rollback

- Keep `TVBOX_U2_ENABLED=false`; revert workflow/code with normal commits; delete only unpublished identity-exact canary draft/tag/refs; never force-push; never delete/move published immutable Release; never touch signing secrets; Drive docs revert via prior snapshots.
