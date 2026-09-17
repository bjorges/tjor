# Design — canonical root representation

## Context

Re-review of v0.17.1 (2026-09-17); both findings verified before this
change: the non-git workspace fallback is `ws="$(pwd)"` (logical) while
`git rev-parse --show-toplevel` and the extras' `pwd -P` are physical —
confirmed by direct comparison through a symlink; and the reviewer's
trailing-slash repro against the shipped image showed the misclassified
read-only child registered as `<child>` + `<child>/*` (fully writable
classification), because the entrypoint compares its normalized entry
against the raw `TJOR_RO_DIRS` line.

## Decisions

1. **Physical canonicalization at the one workspace source.** The
   non-git fallback becomes `pwd -P`; the qualified-id fallback used by
   `--session` resolution follows suit. Git workspaces are already
   physical via `--show-toplevel`, so the normal case is byte-identical.
   The only behavior change is the session id of a *non-git* workspace
   reached through a symlinked cwd — recorded in the CHANGELOG.
2. **One normalization pass in the entrypoint, one shared result.** A
   `_norm_root` helper normalizes (strip trailing slashes) and validates
   (absolute; no CR; no `//`, `/./`, `/../`, trailing `/.`/`/..`; not
   `/`, `*`, or trailing `/*`). Step 3 runs BOTH lists through it into
   normalized arrays, requires RO ⊆ SAFE, refuses cross-class ancestry,
   and registers from the normalized values; the normalized lists are
   handed to step 6 so the kernel-wrap read/write split classifies from
   the same representation. No callsite compares raw env text anymore.
   *Alternative rejected:* full realpath canonicalization in-container —
   the paths name host mounts; resolving them against the container fs
   would judge the wrong namespace. Launcher-side physical paths plus
   strict spelling rules for direct starts cover the boundary.
3. **RO ⊆ SAFE, and RO-without-SAFE refused.** A read-only root that is
   not an approved root has no meaning in the contract; treating it as
   anything (ignored, writable, read-only) invites the next spelling
   bypass, so it is a boundary error.

## Risks / Trade-offs

- [Session-id change for symlinked non-git workspaces] → edge of an edge
  case; stated in the CHANGELOG; git workspaces unaffected.
- [Strict spelling rules refuse exotic-but-real paths (`//`, CR)] → such
  paths never come from the launcher (which canonicalizes); a direct
  invoker can respell canonically.

## Migration Plan

No stored state. Rollback = revert.
