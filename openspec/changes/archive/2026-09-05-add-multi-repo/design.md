# Design: add-multi-repo

*(Added after archival, per the v0.5 external review — `--dir` has real
security-adjacent surface (arbitrary writable host mounts) and warranted a
design record.)*

## Context

`tjor run` mounts one git toplevel at its host path. Multi-repo work needs
several repos in one session. The launcher already resolves the workspace and
runs the agent via `compose run`.

## Goals / Non-Goals

**Goals:** mount additional repos at their host paths (same-path fidelity,
L15), writable; primary workspace still anchors the session (id/identity/cwd).

**Non-Goals:** per-repo identity headers; auto-discovery of related repos;
cross-repo credential scoping.

## Decisions

- **Extra mounts via `compose run --volume host:host`** — no compose-file
  change, no per-session override. Each `--dir` is resolved to an absolute
  path, existence-checked, then VM-share-verified (`verify_bind_source`, after
  the proxy image exists) before mounting.
- **Session identity is anchored to the primary** — extra dirs are mounts, not
  identities; `--session <name>` is the way to isolate.
- **git trust is scoped, not `*`** — the entrypoint marks `safe.directory` for
  exactly the mounted paths (workspace + `--dir`), passed via `TJOR_SAFE_DIRS`.

## Risks / Trade-offs (the security surface the review flagged)

- **`--dir` mounts host paths read-write into the agent** — the very thing the
  cage exists to constrain. Sensitive paths (filesystem root, `/etc`, the home
  directory or an ancestor, and credential dirs `~/.ssh`, `~/.aws`, `~/.kube`,
  `~/.gnupg`, `~/.docker`, `~/.config`, `~/.gcloud`, `~/.azure`) are **refused**
  unless `--unsafe-dir` is given. `--dir` values are deduped (against the
  primary and each other). The operator still chooses what to mount; the
  guardrail stops the *silent* dissolution of the boundary for obviously
  dangerous roots.
- **A `--dir`'d third-party repo's git config is trusted** (needed so git
  operates across ownership mismatch): its `.git/config` (`core.fsmonitor`,
  pager, hooks) could be hostile. Bounded by the cage — non-root agent (uid-0
  refused) and no direct egress — and by the operator having explicitly chosen
  to mount it. Scoping `safe.directory` to the mounted paths (not `*`) limits
  this to those repos rather than every path. See ADR 0008.

## Verification

`tests/integration/multirepo_test.sh`: two repos mounted at host paths, both
writable, git works in each, session id from the primary, and a nonexistent
`--dir` aborts. (Sensitive-path refusal and dedup are enforced in the launcher
and covered by unit-level reasoning; a live case can be added.)
