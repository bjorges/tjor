# Design — refuse mixed-writability mount overlaps

## Context

See proposal.md. One policy defect across two releases, three symptoms
(release review, 2026-09-17; confirmed by code reading against
`bin/tjor` and `images/agent/entrypoint.sh`):

- The `--dir`/`--dir-ro` conflict check compares resolved paths for exact
  equality only; nesting across classes is accepted.
- Docker nested binds: a writable child bind under a `:ro` parent bind is
  writable at the child mountpoint — mount metadata contradicts the
  "read-only tree" claim.
- v0.17.0 registers `<root>/*` git trust per writable root; a read-only
  child nested inside is covered by the parent's star, defeating the
  RO-exact-trust decision that same release made deliberately.
- Landlock rules are additive: `--allow-write <parent>` (or the
  project-dir grant) already covers a nested read-only child;
  `--allow-read <child>` adds nothing and revokes nothing.

## Goals / Non-Goals

**Goals:** make the state that falsifies the guarantees unreachable, on
both the launcher and non-launcher paths; keep the check component-safe.

**Non-Goals:** subtractive Landlock grant construction (complex, fragile,
and unnecessary once overlaps are refused); restricting same-class
nesting (no guarantee is contradicted by it).

## Decisions

1. **One shared refusal, launcher-side, after canonicalization.** In
   `cmd_run`, after both extras lists are resolved (and the workspace is
   known), every read-only root is checked against every writable root
   for containment in both directions with the bash pattern
   `[[ "$a" == "$b"/* ]]` — the `/` in the pattern makes it
   component-boundary-safe (`/a/bc` does not match `/a/b/*`). Paths are
   `pwd -P`-canonicalized already; no trailing slashes exist at this
   point. *Alternative rejected:* fixing each symptom separately
   (mount-order rules, star-suppression under RO children, subtractive
   kernel grants) — three mechanisms to keep coherent versus one refusal.
2. **Entrypoint re-refuses from the env lists.** Same defense-in-depth
   split as the degenerate-root guard: the trust-registration step first
   collects the normalized root list, validates cross-class containment
   against `TJOR_RO_DIRS`, and exits with the boundary code on a hit —
   a direct `docker run` with a contradictory root set must not start
   looking protected.
3. **Same-class nesting stays allowed, and the spec says so.** Two
   writable overlapping roots (or two read-only ones) produce redundant
   but consistent mounts, trust, and grants. Refusing them would break
   legitimate layouts (a repo plus its parent) for no guarantee gained;
   an explicit scenario prevents a future "tidy-up" from banning it.

## Risks / Trade-offs

- [A previously launching layout now aborts] → it was silently violating
  the read-only claim; the error names both roots and the reason.
  Recorded as behavior-change in the CHANGELOG.
- [String-prefix bugs] → containment uses `"${a}" == "${b}"/*` (component
  boundary built into the pattern) and the sibling non-conflict is a
  test, not a hope.

## Migration Plan

No data changes. Operators with a nested mixed layout must split it
(mount the individual repos in the intended class). Rollback = revert.
