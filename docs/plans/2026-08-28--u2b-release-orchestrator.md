# U2b/U2c Release Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install the formal U2 release orchestrator behind `TVBOX_U2_ENABLED=false`, configure production approval / immutable Release / merge-method / release-signing branch policy, prove production-shape canaries and recovery without publishing a disposable immutable formal release, then enable U2c with a no-op smoke.

**Architecture:** U2 observes a human-merged valid U1 candidate PR (automatic mode) or a `slashinchi` manual dispatch on the current `patched` HEAD (manual-local mode), derives a deterministic version-only prep commit, calls the existing isolated `rc-pipeline.yml` for build/sign/verify/attest, requires one exact `release-production` approval bound to version/release-SHA/debt/APK-SHA/run/attempt, then promotes via a dedicated GitHub App token (release identity) performing CAS fast-forward, draft+tag creation, immutable publish, and forward-only `update.json` reconciliation.

**Tech Stack:** GitHub Actions (`workflow_call`, `workflow_dispatch`), Python 3 (unittest, YAML-aware contract tests), GitHub REST API via `gh`, pinned full-SHA Actions, existing `u2_release.py` / `rc-pipeline.yml` primitives.

## Global Constraints

- `TVBOX_U2_ENABLED=false` through U2b; set `true` only in U2c final cutover.
- N1 native 16 KiB debt deferred to 2026-09-28 upstream observation; GitHub releases may carry exact attested `known-debt/3` but must never claim Play/API-35/16KiB readiness.
- No new `rc-control-v2`; `release-signing` remains single-Environment, expanded to exact `patched` + retained `rc-control-v1`, no recurring signing approval.
- Only one `release-production` Environment approval before immutable publication; approval binds exact version/release-SHA/debt/APK-SHA/run/attempt.
- Automatic mode accepts only real U1 PR merge commits; manual mode accepts only `slashinchi` dispatch on current `patched`, no arbitrary SHA/tag/version input.
- Repository merge commits only (merge-commit-only), disabling squash/rebase; immutable releases enabled for future Releases only (historical `v2.1.26.1` unaffected).
- All external Actions remain full-SHA pinned; no unrelated Action upgrades.
- The Mac host is not an Android build environment; all Android work runs on GitHub `ubuntu-24.04`.
- Signing secrets remain Environment-only; never export/copy/print secrets.
- Debt classification: exact current `known-debt/3/three-paths` or upstream-fixed `clean/0/[]` pass; any other native state fails closed.
- `rc-control-v1` tag remains immutable (zero bypass); `rc-control-*` naming reserved.
- U2b canaries use disposable `u2-canary-*` shadow refs and draft Releases; never a formal `v*`, never publish.
- U2c success = production `u2-release.yml` with `TVBOX_U2_ENABLED=true` computes baseline/debt then stops before prep/sign/publish; non-empty control-plane debt is not activation failure.
- `patched` remains the fork user-facing branch; `main` remains the upstream mirror only.

---
