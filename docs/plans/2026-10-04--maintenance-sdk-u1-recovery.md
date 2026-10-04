# Batch Handoff: SDK / CI Repair and Full U1 Recovery

- Batch ID: 2026-10-04--maintenance-sdk-u1-recovery
- Updated: 2026-10-04
- User approval: “同意推荐方案。” following the one-shot SDK/CI + full U1 implementation plan.
- This Batch is the task contract and evidence record. It does not grant execution authority: read the fixed Entrypoint and current Master; implementation requires Master Status=AUTHORIZED for this Batch.

## 1. User Result and Observable Success

Restore the maintenance pipeline rather than change the installed app. Repair the obsolete setup-android default package failure in ordinary CI and U1, then run the complete authorized U1 path: validate the upstream candidate, fast-forward fork main, create the candidate branch and PR, and close matching recovered automation failure issues. Leave the upstream candidate unmerged and production release unchanged. Do not add an artificial dry-run stage or redesign U2.

The distinct PRs are: (1) the SDK/maintenance fix PR, which may be merged into patched after main-thread verification and normal repository checks; (2) the upstream candidate PR, which must remain open/unmerged for a future separately authorized review.

## 2. Fresh Baseline and Preserved Workspace

GitHub readback on 2026-10-04:
- Product patched: 65158965915f0ae4f0b694391eb37a6a11f8f22b.
- Fork main: 6aabea8965a45df9a126d0436404ae8afccfe96f.
- Upstream main (kukuqi666/TVBoxOS-Mobile): a7fe0423cb6b1609398117af4bc7b90cd3ecd8d9.
- Control main: 6f2116eaca56edcc4b392da15f7553e6a74ef61c; no changes authorized there.
- No active product Actions runs or open PRs at preflight.
- Issue #47 OPEN: candidate-validation-failure marker for full upstream SHA a7fe0423cb6b1609398117af4bc7b90cd3ecd8d9.
- Latest monitor run 37195891381 is not recovery evidence: date gate succeeded, but fixture/probe/candidate/write/recovery jobs were all skipped.
- TVBOX_U2_ENABLED=true, unchanged. No U2 variable/settings changes authorized.
- Formal Release v2.1.26.1, release ID 372751097. APK asset ID 520227824, SHA-256 df1760aa82a60c78da88655cdbbf2f2caec2e60c141cef3e78e1b63f314a57ce. Metadata asset ID 520227823, SHA-256 58b7f95c36b66715b3964d88e31f6f75a3fb9368102a600eda3a1eadf149a7f1.
- patched update.json blob: 75e4a9c322e128a77927cf2dc9cef95a27291c4e.
- patched gradle/verified-releases.json blob: 7b85bbc66f0dd137b2fd479d7724d5ca0a043748 (ledger baseline target b187b6ff8d89525da30e2543ed77e8e55bc58b2c).

Protected old workspace: /Users/msy/Documents/Code/Oneplus/TVBoxOS-Mobile-Fork/TVBoxOS-Mobile, branch u2c-canary-secret-inherit-20260901, HEAD 78e64dfd78e074d55c8b4a1a7fcca274d3079185. Never switch/reset/clean/stash it, never stage its changes, never read/change/delete its untracked files. Preserve the five tracked modifications including 55 historical timeline lines. The relevant binary diff SHA-256 is 239742918e75867ac911de46dc0b0f0f84f40c870b249a7f1e14d7b423a7e236. Fresh individual untracked-name enumeration at preflight: 275 files, name-list SHA-256 bc47866e649fa4141526df02404aa43dadf7b3f4c42160f0e14b72989dff8164; historical summary entry counts are not equivalent to file count.

Implementation workspace: /Users/msy/Documents/Code/Oneplus/TVBoxOS-Mobile-Fork/TVBoxOS-Mobile/.worktrees/maintenance-sdk-20261004, new branch maintenance/sdk-u1-recovery-20261004 based on freshly verified origin/patched. It must start clean. Use this explicit linked worktree rather than temporary harness isolation, so results remain available for review/resumption.

## 3. Authorized Change and Remote Operations

Modify only:
- .github/workflows/build.yml
- .github/workflows/upstream-monitor.yml
- AGENTS.md (startup, Master authority, Batch recording/state terminology only; preserve branch/signing/security boundaries and do not reopen U2c)
- Necessary existing tests, primarily scripts/tests/test_upstream_monitor.py and, only if needed, scripts/tests/test_u2_release.py
- docs/plans/2026-10-04--maintenance-sdk-u1-recovery.md
- outputs/logs/2026-10-04--maintenance-sdk-u1-recovery.md (append-only execution log; do not force-add ignored outputs without a reviewed reason)

At each of the two pinned android-actions/setup-android steps, add:

```yaml
with:
  packages: platform-tools
```

Retain android-actions/setup-android@9fc6c4e9069bf8d3d10b2204b1fb8f6ef7065407 and the separate API 34 / build-tools 34.0.0 installation. No unrelated action/dependency upgrades, new dependencies/CLI/hooks/skills, dry-run mechanisms, or broad code refactors.

Remote permission includes: normal git fetch into repository objects; create/push the reviewed maintenance branch; create a maintenance PR based on patched; main-thread-approved normal merge of that maintenance PR (no admin bypass); full U1 workflow_dispatch with force_check=true on patched, or reuse a qualifying scheduled run; U1's existing minimum write/recovery jobs may fast-forward fork main, create automation/upstream-<full-SHA> and a candidate PR, comment/close correctly matching recovered automation issues. No direct manual substitute for U1 candidate writing.

Drive permission: main thread may accept/close the Framework migration, create this Batch, authorize it in Master, and maintain this Batch/Master after implementation and acceptance. Executors do not self-authorize, close a Batch, or alter historical migration, Protocol, DECISIONS, legacy ACTIVE-PLAN/FACTS/HANDOFF. Executor evidence stays in the worktree log/result; main thread performs Drive state writes.

## 4. Implementation and Checks (Main-thread Plan)

1. Main thread: verify current Entrypoint -> Master -> migration Batch; accept migration based on its actual success criteria, create this Batch and set Master AUTHORIZED with this exact scope. Re-read remote Master/Batch before implementation.
2. Executor-grok: verify no relevant drift, fetch origin patched after authorization, create the explicit isolated worktree/branch, read affected files completely, apply only the minimal two SDK settings, update stale AGENTS framework references, add targeted regression tests, and write the reusable approved plan and append-only log.
3. Targeted tests: use the existing uv-managed Python 3.12 (/Users/msy/.local/share/uv/python/cpython-3.12.11-macos-aarch64-none/bin/python3.12) with PYTHONDONTWRITEBYTECODE=1 and PYTHONPATH set to the implementation root. No dependency install or new Python packaging project is required for these standard-library tests. Run scripts/upstream_monitor.py fixture-test; scripts/tests/test_upstream_monitor.py; scripts/tests/test_u2_release.py. Tests must bind each packages assertion to the intended job/step, not a global substring. Include negative regression evidence (removing either setting independently must fail its corresponding test); keep temporary mutants confined to newly created worktree tmp and restore tracked files before commit.
4. Main thread reviews exact file diffs/full affected files and test evidence before any commit/push. Executor then commits only the reviewed whitelist, pushes the maintenance branch, opens the PR, obtains successful real ordinary CI plus APK artifact evidence, and returns. Main thread verifies PR checks, exact SHA/diff and branch protections before merging the maintenance PR normally. An execution checkpoint is not a new user-approval gate.
5. After merge, run/reuse a full U1 at the current patched SHA and intended upstream full identity. Collect direct job evidence showing SDK init and candidate build success, ordinary-CI debug artifact identity (U1 itself has no artifact uploader; do not add one), validated tree, actual candidate tree, full upstream marker/PR identity, fork main FF, and recover job / Issue #47 closure. Do not treat an off-day/skipped green run as success. If upstream identity or relevant baseline materially changes, hand the specific facts to main thread rather than expanding authorization or creating a second candidate manually.
6. Verify the maintenance-merge U2 qualification declines this non-candidate PR and write/signing jobs stay skipped; do not disable U2 or add a new switch. No manual release/recover/noop-smoke triggers. Verify formal Release/tag/metadata unchanged and upstream candidate remains unmerged.
7. Main thread consolidates evidence in this Batch, clears Master authorization and performs outcome acceptance. Executor COMPLETED alone is not acceptance. Retain valid成果; leave candidate review/signing/device installation to a separate authorization.

## 5. Acceptance Evidence

- Both workflows use the intended pinned SDK action with explicit packages=platform-tools, preserve API34 installs, and have targeted positive/negative regression tests.
- Targeted fixtures/tests pass without altering the old workspace.
- Maintenance PR normal CI succeeds, SDK stage and assembleDebug complete, expected debug APK artifact exists (ordinary debug signing only; no production signing Environment).
- Maintenance PR is merged to patched using normal rules after review, exact commit and check identities recorded.
- Full U1 completes at actual repaired trusted patched SHA. Candidate validation and write/recovery take the positive path; fork main reaches authorized upstream; candidate branch/PR retains full upstream SHA/source marker and validated tree matches candidate Git tree. Signed release jobs never run.
- Issue #47 recovery is backed by successful candidate path, matching recovery marker and actual issue state, not merely a fix commit or skipped run.
- Maintenance-merge U2 prep/RC/sign/publish are skipped. Candidate PR is open/unmerged; formal Release v2.1.26.1/tag/update.json/verified-releases remain unchanged.
- Old tracked diff, HEAD and untracked-name baseline preserved. No unrelated repository/control/device changes.

## 6. Expected Risks and Stop/Recovery

The patched release ledger has cumulative local change debt. The existing U2 may open an unapplied-local-delta alert after the maintenance merge; record this accurately and do not close/delete it merely for a green display. This does not mean signing/release occurred, and is not an SDK failure.

Transient network failures: at most two extra retries with 1s/2s gaps. Permissions, wrong parameters or scope failures do not justify retry/bypass/escalation. On timeouts inspect existing outcomes before retrying remote writes.

Within-path local defects may be fixed and directly re-tested. Missing required environment/input -> BLOCKED with artifacts/evidence. Material design/scope/permission/upstream identity conflicts -> NEEDS_REPLAN with exact facts, preserving valid outcomes. Normal required human approval -> HUMAN_ACTION_REQUIRED; no admin bypass.

Before merge, rollback is simply leave/close only the unmerged maintenance PR if necessary. After merge, use a normal reviewed revert PR; no force pushes, hard resets, production-tag changes, bulk deletion or candidate force updates. Successful main FF is an authorized mirror update, not something to reverse by force merely to emulate the old state. Any necessary revert must be scoped and evidence-based.

## 7. Relevant Decisions

- D-062: current lightweight Framework model and Master authority, selectively read when governance wording is needed.
- D-057: U2c closed; no reopen or formal Release live-observation authorization.
No full DECISIONS/history reread is required; current repository code is the factual U1/U2 contract.

## 8. Execution Evidence

2026-10-04 preflight: fresh GitHub/Drive access recovered; relevant baselines matched; main-thread migration acceptance recorded. Implementation has not started at Batch creation. Evidence will be added from actual worktree, PR, Actions and issue readbacks; no future success is asserted here.

2026-10-04 main-thread check: repository only permits merge commits (squash/rebase disabled); required check build-apk must pass. Formal tag ref v2.1.26.1 targets b187b6ff8d89525da30e2543ed77e8e55bc58b2c. U1's current candidate build has no upload-artifact step, so positive U1 acceptance uses real build job/step logs and full validated-tree/candidate-tree/PR identity; the existing ordinary-CI uploader supplies debug APK artifact evidence. This clarification avoids unauthorized artifact features and does not change the intended result.
