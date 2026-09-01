# U2c Release State Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden replay, release identity, ledger reconciliation, manual intents, and control-ref retirement so U2c can be enabled without losing or rewriting release state.

**Architecture:** Keep the existing single `release-production` publish job and isolated `rc-pipeline.yml`. Add a pure strict replay validator, expand U1 fork-owned preservation, and make post-delivery metadata a single bounded CAS commit containing both `update.json` and `verified-releases.json`. Add explicit manual intent gates and a trusted no-op barrier; retire `rc-control-v1` only after an exact canary and drain.

**Tech Stack:** Python 3 stdlib/unittest, Bash, GitHub Actions YAML, `gh` CLI, GitHub Contents/Actions APIs, `gws` Drive control plane.

## Global Constraints

- `TVBOX_U2_ENABLED=false` until all code, canary, configuration readback, and cross-review gates pass; no formal `v*`/Release/production `update.json` mutation while false.
- All `.github/workflows/**` changes merge through a PR to `patched`; never force-push or rewrite public history.
- Exactly one `release-production` job remains; approval marker remains exact and bound to release SHA, debt, version, APK SHA, run, and attempt.
- The normal release user action remains one human U1 candidate merge; retry/recovery does not request a second approval unless the exact run/attempt or binary identity changes.
- The source merge parents are `[B,C]`; candidate parents are `[B,U]`; `U` equals the provenance marker and the fixed upstream `refs/heads/main` object observed by qualification.
- Ledger append and `update.json` update occur in one identity-bound metadata commit after immutable and delivery verification; `git push --atomic` is not used to bind a later ledger commit to an already-created tag.
- `release`, `recover`, and `noop-smoke` are mutually exclusive manual intents; trusted no-op reaches no build/sign/publish/issue/ref write job.
- Preserve all fork-owned `.github/**`, `scripts/**`, `AGENTS.md`, `README.md`, `update.json`, and both Gradle trust manifests during U1 candidate generation.
- Use no new Python dependencies and do not modify signing secrets or unrelated app/runtime code.
- FACTS is append-only, HANDOFF is holistic current state, ACTIVE-PLAN is living current plan, and DECISIONS append or supersede.

---

### Task 1: Control-Plane Authorization and Plan Records

**Files:**
- Create: `docs/requirements/2026-09-01--u2c-release-state-hardening.md`
- Create: `docs/plans/2026-09-01--u2c-release-state-hardening.md`
- Drive: HANDOFF, ACTIVE-PLAN, DECISIONS, FACTS

- [x] **Step 1:** Verify Drive HANDOFF, ACTIVE-PLAN, DECISIONS, FACTS against Git HEAD `0f6c1c0529c250efb75772abd4fbcd269b10ea7f`.
- [x] **Step 2:** Set the Drive HANDOFF to `AUTHORIZED` for this exact plan, preserving all non-secret baseline and stop-condition facts.
- [x] **Step 3:** Rewrite Drive ACTIVE-PLAN to this plan and append a decision that supersedes only the conflicting replay, ledger, intent, and retirement clauses.
- [x] **Step 4:** Read back all changed Drive documents byte-for-byte and record their IDs, modified times, and current Git HEAD in the local timeline log.
- [x] **Step 5:** Run the unchanged baseline suite and record `132/132` before code edits.

### Task 2: Strict Replay and U1 Control-Plane Preservation

**Files:**
- Modify: `scripts/u2_release.py`
- Modify: `scripts/upstream_monitor.py`
- Modify: `.github/workflows/u2-release.yml`
- Modify: `.github/workflows/upstream-monitor.yml`
- Test: `scripts/tests/test_u2_release.py`
- Test: `scripts/tests/test_upstream_monitor.py`

**Interfaces:**
- Add `validate_replay_evidence(evidence, expected_upstream_repository, expected_upstream_ref) -> dict`.
- Change `qualify_u1_merge(..., replay)` to consume the structured replay evidence returned by the CLI.
- Extend `qualify-u1` with `--replay-file` containing the JSON evidence object.
- Expand `FORK_OWNED_PREFIXES` to `.github/` and `scripts/`, and add both Gradle trust manifests to explicit fork-owned paths.

- [x] **Step 1: Write failing tests** for non-direct candidate parents, mismatched base, mismatched upstream source/ref, any of the four trees differing, and a valid `[B,C]`/`[B,U]` replay.
- [x] **Step 2:** Run the focused tests and confirm they fail for the missing validator/arguments.
- [x] **Step 3:** Implement the pure validator and CLI JSON path; preserve the existing fail-closed error shape for invalid qualification.
- [x] **Step 4:** Write failing U1 fixture tests proving `.github/**`, `scripts/**`, `gradle/verified-releases.json`, and `gradle/legacy-dependencies.lock.json` remain base-owned when upstream changes them.
- [x] **Step 5:** Implement the expanded ownership set and required post-push tree checks.
- [x] **Step 6:** Rewrite qualification to copy `scripts/upstream_monitor.py` and `scripts/u2_release.py` from `PUSH_BEFORE`, fetch fixed official upstream `main` and fork `main`, rebuild from `PUSH_BEFORE + U`, and pass all parent/tree/source evidence to `qualify-u1`.
- [x] **Step 7:** Run focused tests, then commit the batch.

### Task 3: Verified-Release Ledger and Atomic Metadata CAS

**Files:**
- Modify: `scripts/u2_publish.py`
- Modify: `scripts/u2_release.py`
- Modify: `.github/workflows/u2-release.yml`
- Test: `scripts/tests/test_u2_publish.py`
- Test: `scripts/tests/test_u2_release.py`

**Interfaces:**
- Add `verified_release_entry(...) -> dict` with the complete persisted identity fields.
- Add `reconcile_verified_releases(ledger, entry) -> dict` returning `append` or `exact-reuse`, and rejecting identity conflicts.
- Add CLI `reconcile-verified-releases --ledger --entry --output`.
- Add `verify_verified_releases(metadata_bytes, expected_entry) -> dict` for exact remote readback.

- [ ] **Step 1: Write failing tests** for complete entry construction, exact replay idempotency, same tag/version/target conflict, malformed ledger, and exact JSON byte readback.
- [ ] **Step 2:** Run focused tests and confirm the new functions/CLI are absent or fail.
- [ ] **Step 3:** Implement the pure entry/reconcile/readback helpers with strict full-SHA, SHA-256, version, and positive version-code validation.
- [ ] **Step 4:** Add a CLI round-trip test using temporary ledger and metadata files.
- [ ] **Step 5:** Replace the publish metadata step with a bounded normal-CAS loop: fetch remote `patched`, reread both remote files, reconcile both, commit both files together, push normally, and retry only after a fresh read/rebuild on non-fast-forward.
- [ ] **Step 6:** Make remote read failure, malformed ledger/update, different same-version identity, and retry exhaustion fail closed; keep exact identity recovery idempotent.
- [ ] **Step 7:** Verify both remote blobs byte-exactly after a successful push and commit the batch.

### Task 4: Manual Intent, Trusted NOOP, and Publish Identity Freeze

**Files:**
- Modify: `.github/workflows/u2-release.yml`
- Modify: `scripts/tests/test_u2_release.py`

- [ ] **Step 1: Write failing structural tests** for `release/recover/noop-smoke` choice inputs, actor/ref/expected-SHA validation, mutually exclusive routing, and a no-op dependency barrier covering every build/sign/publish/issue/ref-write job.
- [ ] **Step 2: Run the structural tests and confirm the current workflow fails them.
- [ ] **Step 3:** Add the explicit dispatch intent contract and pass the intent through gate, qualify, prep, summary, watch, and publish outputs.
- [ ] **Step 4:** Add hard `noop != true` guards to all substantive jobs; make `noop-smoke` compute baseline/debt only and stop before any write-capable job.
- [ ] **Step 5:** Add final live baseline/version collision revalidation before CAS promote, then re-read the Release/tag/draft identity after the first create/asset operation and require exact target, tag, version, asset names, and digests for all later steps.
- [ ] **Step 6:** Add structural assertions that no publish path uses `gh release publish`, `--clobber` for uploads, tag movement, or a second APK build.
- [ ] **Step 7:** Run all U2 tests, shell/YAML checks, and commit the batch.

### Task 5: Canary Harness, `rc-control` Retirement, and Remote Validation

**Files:**
- Create: `.github/workflows/u2-canary-harness.yml`
- Modify: `.github/workflows/rc-control.yml` only if the canary requires an explicit deprecation guard
- Modify: `scripts/tests/test_u2_release.py`
- Modify: `docs/plans/2026-09-01--u2c-release-state-hardening.md`

- [ ] **Step 1:** Add structural tests requiring dispatch-only actor gating, exact run-owned canary namespace, no production tag/Release/update writes, same `rc-pipeline.yml` reference, and `always()` cleanup.
- [ ] **Step 2:** Implement the harness with exact-run cleanup; it may use temporary drafts/refs only and must never wildcard-delete `rc-control-*`, formal `v*`, Releases, rulesets, or policies.
- [ ] **Step 3:** Merge workflow changes through PR, run the harness with `TVBOX_U2_ENABLED=false`, and verify signer, APK, full SAN workflow identity, attestation, and zero residue.
- [ ] **Step 4:** Drain Actions runs, queued runs, and pending deployments before changing any reviewer or signer ingress policy; record the readback.
- [ ] **Step 5:** Disable `rc-control-v1` ingress and remove its workflow/tag policy only in a separate PR after canary evidence; if any active consumer or cleanup residue remains, return `REVIEW_PENDING` instead of deleting broadly.
- [ ] **Step 6:** Re-run local and remote CI, verify formal Release `v2.1.26.1`, production `update.json`, signing secrets, and `TVBOX_U2_ENABLED=false` are unchanged.

### Task 6: U2c Enablement and Closeout

**Files:**
- Drive: HANDOFF, ACTIVE-PLAN, DECISIONS, FACTS
- GitHub repository variable: `TVBOX_U2_ENABLED`

- [ ] **Step 1:** Run executor evidence review and Gemini 3.7 Flash high copy review; use Grok 4.6 xhigh only if a frontend task exists (none is planned).
- [ ] **Step 2:** Fix all P0/P1/P2 findings and rerun the complete verification suite.
- [ ] **Step 3:** Read back Environment, reviewer, immutable-release, ruleset, signer workflow, active runs, and canary residue state.
- [ ] **Step 4:** Set `TVBOX_U2_ENABLED=true` as the last setting change only after all prior evidence is green.
- [ ] **Step 5:** Run the enabled `noop-smoke` dispatch and verify it stops before prep/build/sign/publish/issue/ref writes.
- [ ] **Step 6:** Write Drive HANDOFF to `REVIEW_PENDING`, append FACTS and the final decision, and stop before the first formal Release live-observation batch.

## Rollback

- Before any remote policy change, save non-secret Environment, ruleset, ref, workflow, and variable snapshots.
- If implementation or canary fails, keep `TVBOX_U2_ENABLED=false`, revert code through normal PR commits, and leave published tags/Releases untouched.
- Metadata failures repair only descendant `patched` files; never delete or move an immutable Release/tag.
- Canary cleanup may delete only exact unpublished run-owned objects. It may not delete production refs, Releases, rulesets, or signing secrets.
- Any mismatch between Drive authorization and GitHub state returns `NEEDS_REPLAN` or `REVIEW_PENDING / HUMAN_ACTION_REQUIRED`; no silent improvisation.
