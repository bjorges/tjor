# Refuse overlapping mount roots with different writability

## Why

The v0.16.0 `--dir`/`--dir-ro` conflict check tests only exact path
equality, so roots of different writability classes can nest — and a
release review of v0.16.0/v0.17.0 showed that one gap falsifies three
shipped guarantees at once: a writable child bind under a read-only parent
stays writable (Docker nested mounts), a writable parent's `<root>/*` git
trust reaches repositories inside a nested read-only child (defeating
v0.17.0's deliberate exact-only trust for RO roots), and Landlock's
additive grants mean a broad writable-parent grant already covers a
read-only child (`--allow-read` cannot subtract). One shared control fixes
all three: mixed-writability overlaps must be impossible at launch.

## What Changes

- After path canonicalization, the launcher SHALL refuse any
  ancestor/descendant overlap between a read-only root and a writable root
  (the workspace or a `--dir` extra), in **both directions**, using
  component-boundary containment (`/a/b` conflicts with `/a/b/c`, never
  with `/a/b-other`).
- The entrypoint independently re-refuses (boundary exit code) for
  non-launcher starts, from the `TJOR_SAFE_DIRS`/`TJOR_RO_DIRS` lists —
  the same defense-in-depth split as the degenerate-root guard.
- Same-class nesting (writable under writable, read-only under read-only)
  remains allowed — it produces no contradictory guarantee.
- Tests cover both nesting directions, both flag orderings, the workspace
  as the writable parent, the sibling name-extension non-conflict, and the
  entrypoint-side synthetic refusals.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `session-launch`: new requirement — mount roots of different writability
  classes never overlap (launch refusal, both directions, component-safe;
  sibling names and same-class nesting unaffected).

## Impact

- `bin/tjor` (cross-class overlap check in `cmd_run` after resolution),
  `images/agent/entrypoint.sh` (list-level validation before trust
  registration), `tests/integration/multirepo_test.sh`, README, CHANGELOG.
- Restores as always-true: the `--dir-ro` whole-tree guarantee
  (session-launch), read-only exact-only git trust (session-launch), and
  the kernel/mount read-only agreement (kernel-sandbox — no spec text
  change needed; the situation that falsified it becomes unreachable).
- Breaking only for launches that were already silently broken: a
  previously accepted nested mixed-writability layout now aborts with a
  clear error naming both roots.
