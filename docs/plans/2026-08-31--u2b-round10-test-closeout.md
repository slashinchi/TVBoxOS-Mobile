# U2b Round-10 Test-Contract Closeout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the round-10 cross-review P2 findings without changing any runtime behavior: bind the comment-stream `jq -j -r` test assertion to the same command line that carries `gsub(`, and remove the residual ambiguity in the ACTIVE-PLAN approval constraint.

**Architecture:** The approval gate (`matched == 1` exactly-one current-attempt marker) is intentionally unchanged; Gemini's `>= 1` proposal conflicts with spec §3.7, D-041, D-046 and the HANDOFF stop conditions and is rejected. The fix is a test-contract tightening (same-command-line assertion) plus a control-plane wording clarification.

**Tech Stack:** Python 3 unittest (structure assertions), Bash, GitHub Actions YAML, `gh` CLI, `gws` for Drive control plane.

## Global Constraints

- `TVBOX_U2_ENABLED=false` throughout; zero formal side effects (`v*` tag/Release/`update.json` untouched).
- All `.github/workflows/**` changes merge via PR to `patched`; this batch touches no workflow file, so only the test file is PR-gated.
- No force push, no `--clobber`, no new Python dependencies, no runtime behavior change.
- Approval contract stays: every approved record's actor must be `slashinchi`; exactly one record carries the current-attempt marker (`matched == 1`); older-attempt approvals within the same RUN_ID are tolerated as history.
- FACTS append-only; HANDOFF holistic rewrite; ACTIVE-PLAN living; DECISIONS append/supersede.
- Keep diffs minimal; do not refactor unrelated code.

---

## Task 1: Plan + Drive authorization (control plane)

- [ ] **Step 1:** Write this plan document.
- [ ] **Step 2:** Drive HANDOFF → `AUTHORIZED` (scope-limited: round-10 test-contract batch only), byte-equal readback. FACTS/DECISIONS/ACTIVE-PLAN updated at closeout (Task 6), not now.

## Task 2: Tighten the comment-stream test assertion (TDD)

**Files:**
- Modify: `scripts/tests/test_u2_release.py:1114-1120`

- [ ] **Step 1:** Replace the two cross-section `assertIn` checks with a same-command-line binding assertion inside `test_u2_publish_chain_supports_published_recovery_and_preflight_gates`:

```python
# The comment stream must use `jq -j` so the NUL separator is the only
# delimiter. These two tokens MUST live on the SAME jq command line:
# a regression to `jq -r` on the comment stream would otherwise satisfy
# separate cross-section asserts (the actor stream already contains
# `jq -j -r`), leaving the blind spot unflagged.
comment_lines = [
    line for line in approval_step["run"].splitlines()
    if ".[].comment // " in line
]
self.assertEqual(len(comment_lines), 1, approval_text)
self.assertIn("jq -j -r ", comment_lines[0])
self.assertIn("gsub(", comment_lines[0])
```

- [ ] **Step 2:** Run the single test; expect PASS on current 0a34d4d (line exists exactly once with both tokens).
- [ ] **Step 3:** Negative demonstration: temporarily replace `jq -j -r` with `jq -r` on the comment line only (actor line untouched) → the OLD two-assert form would still pass; the NEW binding assert FAILS. Revert the mutation; re-run PASS.
- [ ] **Step 4:** Commit only the test change on topic branch `u2b-closeout-test-contract`.

## Task 3: Full local verification

- [ ] **Step 1:** `python3 -m unittest discover -s scripts/tests -v` → 132/132 PASS.
- [ ] **Step 2:** `python3 -m py_compile scripts/u2_release.py scripts/u2_publish.py` PASS.
- [ ] **Step 3:** Ruby YAML parse all `.github/workflows/*.yml` PASS.
- [ ] **Step 4:** `bash -n` on all shell scripts in `scripts/` PASS.
- [ ] **Step 5:** `git diff --check` PASS.

## Task 4: PR + remote CI

- [ ] **Step 1:** Open PR `u2b-closeout-test-contract` → `patched` (only `scripts/tests/test_u2_release.py` + this plan doc if in-repo).
- [ ] **Step 2:** Merge via PR. Verify remote CI: `build-apk` SUCCESS + U2 gate SUCCESS (release jobs skipped, flag=false).
- [ ] **Step 3:** Re-run full local suite on merged HEAD; confirm 132/132.

## Task 5: Log

- [ ] **Step 1:** Append `outputs/logs/2026-08-31--timeline.md` (append-only) with the round-10 summary, evidence, verification results.

## Task 6: Drive closeout

- [ ] **Step 1:** ACTIVE-PLAN constraint reworded to the unambiguous two-clause contract (all approved actors `slashinchi`; exactly one current-run/attempt marker match; only historical attempts within the same RUN_ID permitted).
- [ ] **Step 2:** DECISIONS append D-047 (test blind spot fixed; `>=1` proposal rejected with rationale; control-plane wording clarified).
- [ ] **Step 3:** FACTS append round-10 evidence (executor + Grok/Gemini findings, fix, verification, CI runs).
- [ ] **Step 4:** HANDOFF holistic rewrite → `REVIEW_PENDING` (byte-equal readback on all four docs).

## Task 7: Final cross-review

- [ ] **Step 1:** Dispatch Grok 4.6 xhigh + Gemini 3.1 Pro high on merged HEAD; expect CLOSE_READY.
- [ ] **Step 2:** Report to planning role for U2b close; U2c remains a separate authorized batch.

## Rollback

- If merge not yet done: close PR; delete topic branch. If merged: normal revert PR of the single test commit.
- Drive: rewrite current-state docs to actual HEAD; FACTS is append-only (no deletion), corrections are appended.
- Never touch `TVBOX_U2_ENABLED`, formal Release/tag/`update.json`, or signing secrets.
