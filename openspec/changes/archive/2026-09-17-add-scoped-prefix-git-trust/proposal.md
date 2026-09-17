# Scoped prefix git trust for mounted trees

## Why

git trust (`safe.directory`) is registered once at container start, for
exactly the operator-approved mount roots — and git's exact-string matching
means that covers *only those directories themselves*. A repo or worktree
created **during** the session under an approved root (the standard
"`git worktree add`, then work in it" first step of a task) hits a
dubious-ownership refusal every time, and a mounted parent directory of many
repos (`~/git/spv/`) buys filesystem access but no git trust for anything
inside it (#53). The issue asked for a mechanism that extends trust
dynamically without falling back to `safe.directory = *`; it also asked to
re-check whether upstream git had grown a scoped mechanism — it has, and the
shipped image already carries it.

*Revised after a four-lens external review (2026-09-16): tree trust is now
scoped to writable roots, the wildcard-degeneration guards and real
(non-vacuous) tests were added, and the git version floor became a build
gate. The mechanism itself was endorsed by all four reviewers.*

## What Changes

- **The entrypoint registers each WRITABLE approved mount root as a tree,
  not a point**: for every writable `TJOR_SAFE_DIRS` entry (the workspace
  and `--dir` extras) it adds both `<root>` and `<root>/*` to system git
  config. git ≥ 2.46 gives trailing-`/*` entries prefix semantics (the
  image ships git 2.47.3; semantics verified empirically in the image —
  nested repos at any depth under the starred root are trusted, sibling
  paths like `<root>-evil` and paths outside stay refused).
- **Read-only roots (`--dir-ro`) keep exact-match registration.** The
  dubious-ownership refusal is a real protection for unvetted pre-existing
  content: git refuses to honor *any* config in an untrusted repo, so a
  hostile nested `.git/config` (fsmonitor, pager, filters, hooks, a
  repo-local credential helper) never executes during `git status`/`log`.
  `:ro` blocks writes, not config execution — and a read-only investigation
  mount is exactly where hostile pre-existing content is expected. Nothing
  of the #53 headline fix is lost: nothing new can be created under a `:ro`
  mount, so mid-session worktrees and clones only ever happen under
  writable roots. The trade-off given up: git reads in nested repos under a
  `--dir-ro` *parent* stay refused — mount the individual repos `--dir-ro`
  (each gets exact trust), or mount the parent writable and accept the
  widening.
- **Wildcard-degeneration guards**: a root whose registration would itself
  be wildcard-interpretable — empty, `/`, literally `*`, or ending in `/*`
  — aborts the launch (and the entrypoint independently refuses it, for
  non-launcher starts). Verified: `safe.directory = /*` trusts every path
  on the filesystem, so these degenerate forms are exactly the bare-`*`
  ADR 0008 forbids. Trailing slashes are normalized before registration.
- **Real tests**: on uid-aligned engines git's ownership check
  short-circuits to success before `safe.directory` is consulted (verified
  in-image), so every trust assertion runs under
  `GIT_TEST_ASSUME_DIFFERENT_OWNER=1` (verified effective) — the tests fail
  on a broken or missing implementation. Negative tests pin the boundary:
  sibling-prefix refused, out-of-root refused, symlink escape refused,
  degenerate roots refused at launch.
- **git version floor as a build gate**: git enters the image via the base
  distro's apt, not a pinned download — the ≥ 2.46 requirement is enforced
  by a Dockerfile assertion that fails the build, so a base-image change to
  an older git can never silently ship inert `/*` entries.
- The issue's candidate designs — a root-privileged mediated trust helper,
  a transparent git wrapper, a filesystem watcher — remain rejected
  alternatives (see design.md).

Closes #53.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `session-launch`: new requirement — git trust covers each *writable*
  approved mount root as a whole tree (mid-session-created
  worktrees/repos and nested pre-existing repos included); read-only roots
  stay exact-match; degenerate wildcard-interpretable roots abort; paths
  outside every approved root remain untrusted.

## Impact

- `images/agent/entrypoint.sh` — the safe.directory registration loop
  (starred entries for writable roots only; degeneration guard) .
- `images/agent/Dockerfile` — git version floor assertion (≥ 2.46).
- `bin/tjor` — root validation (degenerate forms die at launch); the
  TJOR_SAFE_DIRS/TJOR_RO_DIRS contract comment updated: the writability
  class is load-bearing for trust eligibility after all.
- `tests/integration/multirepo_test.sh` — the #53 headline flow plus the
  negative suite, all under `GIT_TEST_ASSUME_DIFFERENT_OWNER=1`.
- Docs: README multi-repo + hardened-profile notes (mask_dirs interaction),
  `docs/decisions/0008-*.md` §4, CHANGELOG.
- Fully backward compatible; strictly widens trust *within* already-approved
  writable roots only.
