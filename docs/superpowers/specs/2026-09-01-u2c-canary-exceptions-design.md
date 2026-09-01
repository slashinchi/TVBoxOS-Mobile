# U2c Canary Exceptions Design

Date: 2026-09-01
Status: **AUTHORIZED** (user authorized bounded U2c canary exceptions on 2026-09-01)

## Decision

The U2c canary may use the existing isolated signer job and its
`release-signing` Environment only to produce a disposable, signed test APK
and attestations. It must never publish a formal Release, move a production
tag, modify `main`/`patched`, write production metadata, or change rulesets,
policies, or secrets.

The canary caller and the reusable RC pipeline receive a controlled canary
namespace based on the exact run and attempt, for example
`u2-canary-123-attempt-1`. Every canary artifact name uses that namespace.
Cleanup may delete only exact artifacts owned by that run and attempt; it may
not use wildcard deletion or touch `rc-control-*`, formal `v*`, or Releases.

## Gate And Evidence

- The workflow is `workflow_dispatch` only.
- Both the original actor and the rerun actor must be `slashinchi`.
- The requested ref and live `patched` ref must equal the expected full SHA.
- The harness calls the existing `rc-pipeline.yml` and verifies the signed APK,
  signer identity, full workflow SAN, and both attestations.
- A canary failure or cancellation runs exact-name cleanup and leaves no
  run-owned residue; incomplete cleanup returns `REVIEW_PENDING`.

## Scope Change

Task 5 now includes the minimum reusable-workflow change needed to prefix
canary artifact names. It also updates the project rule and control-plane
requirements to record the explicit signing exception. No production release
path is changed.

## Verification And Rollback

Local tests verify trigger, identity, namespace, permissions, artifact names,
cleanup, and forbidden production operations. The later live gate must run with
`TVBOX_U2_ENABLED=false`, inspect the exact run evidence, drain active runs and
pending deployments, and verify zero residue before any `rc-control-v1`
retirement. If any check fails, leave the flag false and do not retire or delete
broader refs.
