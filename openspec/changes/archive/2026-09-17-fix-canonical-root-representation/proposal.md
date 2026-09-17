# Canonical root representation everywhere the overlap boundary is judged

## Why

The v0.17.1 mixed-writability refusal is sound on the ordinary launcher
path, but a re-review found two bypasses in the same boundary, both about
representation: (1) a **non-git workspace** is recorded with logical `pwd`
while extras are resolved with `pwd -P`, so a symlinked cwd and its
physical read-only descendant do not textually overlap — the launch
succeeds and the writable workspace mount (and its tree-wide git trust)
covers the supposedly read-only subtree through the alias; (2) the
**entrypoint** normalizes `TJOR_SAFE_DIRS` entries but classifies
read-only membership by exact match against the **raw** `TJOR_RO_DIRS`, so
a trailing slash in a hand-provided environment defeats the non-launcher
enforcement — verified: the misclassified read-only child was not merely
un-refused, it was registered with its own `<child>/*` trust. Both fixes
are the same idea: one canonical representation before any classification.

## What Changes

- Launcher: the non-git workspace fallback canonicalizes physically
  (`pwd -P`), matching git's own canonicalized toplevel and the extras —
  applied before session-id derivation, mounts, and overlap checks. (Git
  workspaces are unchanged: `git rev-parse --show-toplevel` already
  resolves symlinks.)
- Entrypoint: both env lists are parsed, normalized, and validated into
  one shared representation **before** read-only classification,
  cross-class ancestry, git-trust registration, and the kernel-wrap
  grants. Malformed spellings for direct invocation are refused
  (boundary exit code): relative paths, `//`, `.`/`..` segments, carriage
  returns, and the existing degenerate forms — now applied to
  `TJOR_RO_DIRS` entries too. Every read-only root must be one of the
  approved roots; a read-only list without approved roots is refused.
- Regression tests for both bypasses: the symlinked non-git workspace
  aborts before Docker, and the reviewer's exact trailing-slash repro
  (plus `..`, `//`, relative, CR, and RO-not-subset variants) exits 90.
- Edge-case behavior change, stated honestly: a **non-git** workspace
  whose cwd path contains symlinks now derives its session id from the
  physical path (previously the logical one). Git workspaces — the normal
  case — are unaffected.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `session-launch`: the overlap requirement gains canonical-representation
  language — physical canonicalization of every root before comparison,
  normalization + strict validation of the non-launcher lists, and the
  read-only-subset rule.

## Impact

- `bin/tjor` (workspace fallback + qualified-id fallback), 
  `images/agent/entrypoint.sh` (shared normalization for steps 3 and 6),
  `tests/integration/multirepo_test.sh`, CHANGELOG.
