# U2c Release State Hardening - Requirements

Date: 2026-09-01
Status: **AUTHORIZED** (user authorized execution on 2026-09-01; implementation remains flag-gated until validation completes)
Supersedes only the conflicting replay, release-ledger, manual-intent, and control-ref retirement clauses in the earlier U2b/U2c documents. D-001, D-011, D-027, D-028, D-029, D-037, D-038, and D-047 remain effective where not explicitly changed here.

## 1. Objective

Make the existing U2 release path safe for repeated releases and recovery without changing the normal user contract:

`one human U1 candidate merge -> strict replay and control-plane verification -> exact RC -> one release-production approval -> immutable Release -> delivery verification -> atomic update.json + verified-release ledger reconciliation`.

The implementation must be testable with `TVBOX_U2_ENABLED=false`; enabling U2c is the final setting change after code, canary, configuration readback, and cross-review pass.

## 2. Release Identity

- Automatic release authority comes only from a `slashinchi` merge of a validated U1 candidate PR into `patched`.
- The source merge must have parents `[B,C]`. The candidate commit `C` must have parents `[B,U]`.
- `U` must equal the provenance marker upstream SHA and the fetched immutable object at `kukuqi666/TVBoxOS-Mobile` `refs/heads/main` observed during qualification. The fork `main` must be an ancestor of `U`.
- Trusted replay rebuilds a candidate from `B` and `U` using the fork-owned `prepare-candidate` helper copied from the pre-merge control snapshot.
- Qualification requires `marker tree == actual candidate tree == rebuilt candidate tree == source merge tree` and all direct-parent identities above.
- A later upstream fast-forward does not alter an already recorded `U`; upstream force-push, missing objects, missing provenance, candidate-not-merged, or fork history rewrite fail closed.

## 3. Control-Plane Protection

- U1 candidate preparation preserves all `.github/**` and `scripts/**` files, `AGENTS.md`, `README.md`, `update.json`, `gradle/verified-releases.json`, and `gradle/legacy-dependencies.lock.json` from the fork base.
- U1 required checks must compare these control inputs against the candidate base and repeat the comparison after candidate push and after the human source merge.
- U1 never executes upstream candidate control code; qualification and replay use the pre-merge trusted snapshot.

## 4. Manual and No-op Intents

- `workflow_dispatch` is accepted only for actor `slashinchi` on `refs/heads/patched`.
- The only legal intent values are `release`, `recover`, and `noop-smoke`; one dispatch carries exactly one intent.
- `release` requires an expected current `patched` SHA and derives the version from the live canonical baseline. `recover` requires the expected source SHA and expected version identity. `noop-smoke` runs only the trusted baseline/debt computation and cannot reach U1 replay qualification, prep, build, sign, publish, issue write, or ref write jobs.
- Any missing, duplicated, malformed, or intent-inconsistent input fails closed. Queue order never grants release authority.

## 5. Ledger and Metadata

- After immutable Release and delivery verification succeed, append a complete identity entry to `gradle/verified-releases.json` and update root `update.json` in the same metadata commit.
- The ledger entry includes tag, target SHA, version name/code, signed APK SHA-256, update.json SHA-256, signer fingerprint, source SHA, debt fingerprint, run ID, run attempt, `verified=true`, and `tag_ancestor=true`.
- Exact full-entry replay is idempotent. The same tag/version/target with any differing identity field is a conflict and fails closed. A different version may append only when live canonical state is readable and monotonic.
- Metadata reconciliation uses bounded fetch/rebuild/push retries on normal non-fast-forward failure. Every retry rereads both remote files and rebuilds one commit on the new remote `patched` HEAD. Read failure, malformed JSON, newer conflicting identity, or retry exhaustion fails closed.
- `git push --atomic` is not used to bind a tag to the later ledger commit; the tag/Release already exists before the post-delivery metadata commit. Published tag/Release objects are never moved or deleted.

## 6. Canary and Retirement

- `TVBOX_U2_ENABLED=false` remains in force through local and remote code validation.
- The explicitly authorized U2c canary may call the isolated signer in the existing `rc-pipeline.yml` and its `release-signing` Environment only to produce a disposable signed test artifact and attestations. It may not publish a formal Release, move production tags/refs, write production metadata, or change secrets, rulesets, or policies. All other temporary canaries remain secret-free.
- Canary artifacts use exact run-owned names such as `u2-canary-<run>-attempt<n>-signed.apk`; cleanup is restricted to exact names and current-run ownership. It never wildcard-deletes `rc-control-*`, formal `v*`, Releases, rulesets, or policies.
- `rc-control-v1` is retired only after a new-code canary proves signer, APK, attestation, workflow identity, and branch/ref policy. Retirement is staged: disable ingress, drain Actions runs and pending deployments, verify no active consumer, then remove workflow/tag policy in a separate change. Any incomplete cleanup returns `REVIEW_PENDING`.
- U2c enablement (`TVBOX_U2_ENABLED=true`) is last, followed by an enabled no-op smoke. The first formal immutable Release remains a separate live-observation batch.

## 7. Acceptance

- All new behavior has failing tests first, then minimal implementation, then full local verification.
- `python3 -m unittest discover -s scripts/tests -v`, `py_compile`, workflow YAML parse, `bash -n`, and `git diff --check` pass.
- No formal `v*` tag, Release, signing secret, or production `update.json` mutation occurs while the flag is false.
- Final cross-review uses executor evidence, Gemini 3.7 Flash high for Chinese control-plane copy, and Grok 4.6 xhigh for frontend work only if a frontend task exists. No frontend task is in this batch.
