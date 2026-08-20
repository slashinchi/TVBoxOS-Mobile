# TVBoxOS-Mobile fork maintenance rules

- `main` is an upstream mirror. Put all local maintenance changes on `patched`; never commit local patches to `main`.
- Before non-trivial work, reconstruct context from the project Google Drive folder in this order: `TVBoxOS-Mobile-Fork-HANDOFF.md`, `TVBoxOS-Mobile-Fork-ACTIVE-PLAN.md`, relevant accepted entries in `TVBoxOS-Mobile-Fork-DECISIONS.md`, and recent FACTS only when evidence is needed. Do not continue from chat/compaction summaries alone.
- GitHub is the source of truth for code/branches/commits/Actions/releases. Reconcile Drive documents against Git before editing.
- If HANDOFF SHA/state disagrees with GitHub, stop implementation, reconcile the mismatch, and update the docs first.
- For complex work, follow ACTIVE-PLAN through implementation and validation; do not re-plan settled decisions unless evidence requires it.
- After each independently verifiable batch: commit to `patched`, run the required build/tests, append verified evidence to FACTS, maintain ACTIVE-PLAN, and rewrite HANDOFF to the new current state.
- Documentation semantics: HANDOFF/current-state = rewrite holistically; ACTIVE-PLAN = living/current; FACTS = append-only timeline; DECISIONS = append or supersede.
- Never store keystores, passwords, tokens, or other secrets in the repo or normal Drive docs.
- Keep diffs minimal. Do not refactor unrelated code or expand scope without evidence.
- GitHub default branch `patched` is the fork user-facing and normal development/PR base; this does not change D-001: `main` remains the upstream mirror only.
- Upstream maintenance follows `upstream/main -> fork/main -> merge fork/patched`; do not use a direct GitHub Sync fork operation into `patched` as the normal path.
- README cleanup removes human-facing promotion and upstream-personal content only; it never authorizes deleting inherited runtime or resource files.
- U1 automation treats upstream content as unreviewed: candidate validation is read-only and has no signing secrets; only the minimum write job may fast-forward `main`, create a candidate branch, and open a PR.
- U1 never auto-merges `patched`, approves a PR, touches `build.yml`, or enters signing, Environment, tag, Release, or update-metadata paths.
- U1 candidate branches use `automation/upstream-<full-40-char-sha>`; human-facing titles may shorten the SHA, but PR/Issue bodies and markers retain the full upstream identity. Never force-update an existing automation PR, and fail closed on non-fast-forward `main`, unsafe conflicts, or permission errors.
- U1 candidate validation records the full validated Git tree; write/recovery paths must compare the actual candidate branch tree to it before opening a PR. GitHub API pagination/retry/reconcile plumbing stays in the trusted Python helper and uses argv-only subprocess calls.
