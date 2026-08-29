# U2b/U2c Release Orchestrator — Requirements & Design

Date: 2026-08-28
Status: **AUTHORIZED** (user approved design 2026-08-28; execution begins after Drive HANDOFF set to AUTHORIZED)
Supersedes (with this spec): D-033 ordering clause "N1 blocks U2b/U2c", D-036 "release-signing entry = rc-control-v1 only", D-007 signed-RC-via-build.yml constraint.
Retains: D-001/D-003/D-011/D-012/D-013/D-014/D-027/D-028/D-029/D-030/D-031/D-032/D-034/D-035.

## 1. Objective

Complete the original post-merge release-management objective in production shape:

`valid U1 candidate merged by human → provenance revalidated → actual merged delta classified → deterministic version → exact release SHA → RC built with no signing secret exposure to repository code → signed RC identity proven → human sees risk/RC evidence → one production approval → exact RC binary promoted without rebuild → immutable tag/Release/update metadata consistent → partial failures recover without moving successful formal release state`.

## 2. Scope

### In scope
- U2b: install `u2-release.yml` behind `TVBOX_U2_ENABLED=false`; add focused publish/state helper; TDD contract tests; configure `release-production`, immutable releases, merge-commit-only, `release-signing` branch policy (exact `patched` + `rc-control-v1`); draft-only canary with failure injection and cleanup.
- U2c: after independent cross-review, set `TVBOX_U2_ENABLED=true` as final setting change; run no-op smoke (compute baseline/debt, stop before prep/sign/publish); close.
- First real immutable U2 Release: separate live-observation batch after U2c closeout.

### Out of scope
- N1 native remediation (deferred to 2026-09-28 upstream check; no self-rebuild this cycle).
- Any new signing Environment, `rc-control-v2`, legacy `v*` tag publisher.
- Changing `gh.xxooo.cf` download-acceleration strategy.
- Replacing the existing `release-signing` secrets.

## 3. Architecture

### 3.1 Release intent
- Automatic upstream mode: push to `patched` that strictly qualifies as a U1 candidate merge (PR lineage, merge parents, candidate tree, upstream SHA/version).
- Manual local-maintenance mode: `workflow_dispatch` by `slashinchi`, targeting only current live `patched` HEAD. No SHA/tag/version input.
- Non-U1 human push debt watcher: read-only comparison of canonical last Release → current `patched`; docs/control-plane-only pushes silent; release-relevant new/changed local debt opens/updates one deduplicated `local-release-debt` Issue.

### 3.2 Version derivation
- Compute cumulative release debt from canonical last formal Release baseline.
- Docs-only never releases; runtime/build/release-sensitive debt requires explicit mode decision.
- If version bump required: single deterministic version-only prep commit (only `app/build.gradle` version fields) bound to source SHA, version, debt fingerprint. Prep refs are disposable.

### 3.3 RC production
- Reuse the existing local `rc-pipeline.yml` (dual-builder, compare gate, isolated signer, verifier, dual attestation). Never rebuild a second publish APK.
- Debt allowlist: exact `known-debt/3/three-paths` or `clean/0/[]`; any other combination fails closed.
- RC summary: mode, integrated/upstream SHA, release SHA, version, classification, changed paths, RC artifact link/run ID, signer fingerprint, APK SHA-256, attestation links, debt fingerprint, smoke recommendation.

### 3.4 Production approval (the only formal gate)
- `release-production` Environment: zero secrets except `TVBOX_RELEASE_TOKEN`; required reviewer `slashinchi`; `prevent_self_review=false`; deployment policy exact `patched`; admin bypass off (UI action, `HUMAN_ACTION_REQUIRED`).
- Approval binds exact marker: `TVBOX_RELEASE_APPROVE_V2 release=<full> debt=<sha256> version=<v> apk=<sha256> run=<id> attempt=<n>`.
- Any rebuilt/re-signed RC, changed APK SHA, or new run/attempt invalidates the earlier approval.

### 3.5 Promotion & publication (post-approval, irreversible)
1. Revalidate source/intent, cumulative debt, prep ref, release SHA, RC identity, artifact digests, attestations, immutable-release setting.
2. Independent re-download + hash + signer/package/version check of signed APK.
3. Promotion state: fresh (`patched == source_sha`) → CAS fast-forward to exact `release_sha`; recovery (`patched == release_sha` or descendant containing it) → continue; otherwise fail closed.
4. CAS/readback = promotion point-of-no-return.
5. Generate `update.json` + release notes inputs from trusted fork control code.
6. Fresh formal version: assert default branch `patched` and `patched == release_sha`; Create Release REST with `draft:true`, exact `tag_name`, `target_commitish=release_sha` (tag+draft one provider op); on ambiguous/timeout, list/reconcile, never blind-retry.
7. Verify tag → exact `release_sha`, unique matching draft.
8. Attach exactly `TVBox-Mobile-v<version>.apk` + `update.json`; no stale/extra assets; API digest + actual download SHA + filename/version identity + exact update.json bytes/URL.
9. Append human-visible `Build / Release Evidence` block (run URL, mode, source PR + upstream SHA or manual-local source, release SHA, debt fingerprint, signed APK SHA, signer fingerprint, canonical `gh attestation verify` command). No secrets.
10. Publish verified draft / mark latest. Never rebuild APK.
11. Require Release `immutable=true`, `gh release verify` PASS, `gh release verify-asset` PASS (consumes GitHub's auto immutable Release attestation).
12. Delivery check: fetch configured `apk_url` (gh.xxooo.cf proxy) with bounded retries/timeouts/redirect-chain; require downloaded APK raw SHA == exact signed RC; also verify direct GitHub asset. Failure → keep metadata at prior valid Release, open identity-bound `release-delivery` incident.
13. Monotonic latest-deliverable reconciliation of root `patched/update.json`; older recovery never overwrites newer metadata; post-commit byte readback.
14. Delete now-redundant prep ref; close release incidents whose conditions are satisfied.

### 3.6 Failure / recovery state machine
- Non-candidate ordinary push → clean skip.
- Invalid candidate / wrong merge / stale tree / baseline mismatch / version collision / unresolvable `human-blocked` → deduplicated incident, no release mutation.
- Prep ref exists, RC not successful → reconcile exact prep identity, reuse same release SHA; patched advanced → recompute cumulative debt, supersede or block old prep.
- RC success, approval pending → newer patched merge invalidates pre-promotion RC (carries forward unreleased debt).
- Approval rejected → record `human-blocked` only on explicit `release-production` review `rejected` by `slashinchi`; operational failures are not user rejection.
- Promotion succeeded, draft not created → retry accepts `patched == release_sha` or descendant; single Create-Release(draft+target_commitish); workflow-file divergence → stop for explicit recovery.
- Draft/tag exists, not published → tag must equal release_sha; reconcile draft assets; expired exact RC → stop (no silent abandon; explicit authorized batch may delete exact matching unpublished draft+tag together).
- Published immutable Release → verify tag/SHA/immutability/exact assets/release attestation; conflicting public identity → fail closed; never replace published immutable APK.
- Metadata push failed → repair only current descendant `patched/update.json` if still newest; never roll back; never delete/move successful tag/Release.
- Prep cleanup idempotent; only after success/supersession/abandonment.
- Every incident keyed by mode + generic source SHA + planned version + debt fingerprint.

### 3.7 Concurrency
- No whole-run concurrency group (30-day approval wait must not block newer RC).
- Qualification/build/sign/attest may run concurrently; revalidate immutable inputs.
- Prep-ref mutation: job-level `tvbox-u2-prepare` concurrency.
- Approval-wait job: not in publish concurrency group.
- Irreversible post-approval publish: job-level `tvbox-u2-publish` concurrency, `queue: max`, no cancel.
- Queue order is never release authority; every prep/publish job recomputes canonical state before mutation.

### 3.8 Trust / permissions
- Caller jobs invoking `rc-pipeline.yml`: max `contents: read` + `id-token: write` + `attestations: write`; no other scopes.
- Builder: `contents: read` only, no Environment/secrets/OIDC.
- Isolated signer: no repo checkout; `release-signing` secrets; no contents/OIDC/attestation write.
- Verifier/attestor: no signing secrets; minimal OIDC + attestation write; no package-manager/repo execution in attestor.
- Publish job: `release-production` Environment only; uses `TVBOX_RELEASE_TOKEN` (fine-grained PAT, `Contents: read+write`, single repo) via GitHub App/token identity; no signing secrets.
- Whole-repo contract test enumerates every `environment: release-signing` consumer and every `contents: write` / `git push` / refs write; exactly one signer consumer in `rc-pipeline.yml`; publish write only in `u2-release.yml`.
- All `.github/workflows/**` changes remain PR-gated; docs/control-plane-only pushes silent.

## 4. U2b / U2c batching

### U2b (installed, disabled)
1. Docs & authorization boundary (Drive HANDOFF=AUTHORIZED; DECISIONS append D-037 superseding ordering).
2. TDD first: extend `u2_release.py` + new `u2_publish.py` + contract tests (approval marker, draft reconcile, identity-bound delivery hold, ruleset-aware CAS/failure semantics, whole-repo signer-consumer enumeration).
3. Install `.github/workflows/u2-release.yml` behind `TVBOX_U2_ENABLED=false`; no real prep/sign/tag/Release/metadata writes when flag missing/not `true`.
4. Configure GitHub: `release-production` (reviewer `slashinchi`, branch `patched`, `TVBOX_RELEASE_TOKEN` secret + expiry variable), immutable releases ON, merge-commit-only, `release-signing` branch policy exact `patched` + `rc-control-v1`. Admin bypass off = `HUMAN_ACTION_REQUIRED` UI action. API readback every step. `TVBOX_U2_ENABLED=false` throughout.
5. Draft-only canary `u2-canary-*`: real patched-caller → existing rc-pipeline → one `release-production` approval → Create Release draft + two assets + failure injections (missing asset then repair; extra asset then reject; stale RC superseded by newer merge; delivery proxy timeout/stale/wrong bytes/redirect). Cleanup to zero residual workflow/ref/PR/draft. No publish.
6. Local verification: 89+ Python tests, `py_compile`, YAML parse, `bash -n`, `git diff --check`; ordinary CI PASS.
7. Independent cross-review (Grok 4.6 xhigh + Gemini 3.1 Pro high + executor evidence). Fix blockers; return `REVIEW_PENDING`.

### U2c (final cutover)
1. Re-verify reviewed U2b HEAD, zero canary residue, settings readback.
2. `TVBOX_U2_ENABLED=true` as the last setting change.
3. Run no-op enabled smoke: production workflow computes baseline/debt then stops before prep/sign/publish; non-empty control-plane debt is not activation failure.
4. Independent review; close U2c.
5. First real immutable U2 Release = separate live-observation batch (single `release-production` approval; post-publish immutable/asset/proxy/metadata verification).

## 5. Acceptance criteria

- Python unit/contract tests, YAML parse, shell syntax, metadata dry-run, ordinary CI, RC regression all PASS.
- Canary proves approval binding, draft repair, stale-RC invalidation, concurrency, cleanup-to-zero.
- U2b end state: `TVBOX_U2_ENABLED=false`, zero formal side effects (no `v*` tag/Release, `update.json` untouched).
- U2c: flag `true` only after independent review; no-op smoke PASS.
- Any formal Release reuses the approved RC bytes only; never rebuilds APK.
- Release evidence explicitly shows `known-debt/3` + three paths; no Play/API-35/16KiB readiness claim.
- Any new/different incompatible native library set fails closed.

## 6. Rollback

- Before GitHub policy mutation, save non-secret Environment/ref settings snapshots.
- On failure: set `TVBOX_U2_ENABLED=false` first; revert workflow/code with normal commits; restore prior merge-method/Environment/ruleset settings from snapshot.
- Unpublished identity-exact canary drafts/tags may be cleaned.
- Published immutable formal Release/tag never deleted/moved; forward-only metadata/delivery repair.
- Never export/replace signing secrets; never force-push; never reset history.
