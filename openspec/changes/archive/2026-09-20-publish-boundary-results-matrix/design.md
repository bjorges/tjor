# Design

## Context

See proposal.md — Why. Verified in the two suites:

- `images/conformance/probes.py`: each adversarial case is `@probe("<name>")` on a function; a `RESULTS` list drives `main()`'s `ok/FAIL <name>` output. The names are stable, human-readable sentences (e.g. `"direct egress bypassing the proxy is impossible"`, `"DNS for an unlisted zone fails closed (NXDOMAIN, no forwarding)"`).
- `tests/integration/landlock_test.sh`: each case is `check "<msg>" …` (and a few direct `ok "<msg>"`), printed as `ok/FAIL <msg>`.
- Generators already live in `python/` (`python/gen_corefile.py`); the doc-lint (`tests/doc_consistency.sh`) already enforces README/doc invariants and is where a new drift check belongs.
- Boundaries map to existing spec capabilities: `cage-network` (egress/DNS/dual-homed/admin-surface), `egress-policy` (carve-out/encoding/default-deny), `credential-broker` (broker injection/leak), `kernel-sandbox` (outside-tree/dotenv/degradation), `session-identity` (x-agent-* forgery/injection).

## Goals / Non-Goals

**Goals:**
- A legible matrix (guarantee → probe → suite → spec) generated from the suite sources, not hand-authored.
- Impossible to drift: a probe added/renamed/removed without a registry update fails the lint.
- No new runtime behavior, no new dependency (stdlib parsing of source files).

**Non-Goals:**
- Live per-run pass/fail in the committed doc (decided with the user: coverage matrix, not run-capture — CI's conformance/landlock jobs remain the live signal).
- Running the suites to build the doc (no docker needed to generate or lint it).
- A new spec capability (this is tooling/docs; `skip_specs: true`).

## Decisions

1. **Parse names from source, don't run the suites.**
   The generator greps `@probe("…")` from `probes.py` and `check "…"` / `ok "…"` from `landlock_test.sh` (stdlib `re`, reading the files). This keeps generation dockerless and deterministic, and ties the matrix to exactly the probes that exist. Running the suites for live status was considered and declined (see Non-Goals); CI already runs them.

2. **A registry in the generator maps probe → (guarantee, spec), cross-checked both ways.**
   A dict keyed by the exact probe/check name gives its human guarantee phrasing and backing spec capability. The generator asserts **set equality** between registry keys and the names found in source: an unmapped probe (new/renamed) OR a registry entry with no matching source probe (stale) is a hard error. This is the anti-drift core — the matrix cannot omit a real probe or list a phantom one.

3. **`--check` mode powers the lint.**
   `gen_boundary_matrix.py` writes `docs/boundary-matrix.md` by default; `--check` regenerates in-memory and exits non-zero (with a diff) if it differs from the committed file, and also runs the registry↔source cross-check. `tests/doc_consistency.sh` calls `--check`, so the existing doc-lint gate (already in CI) enforces it — no new CI job.

4. **Coverage status, phrased honestly.**
   The matrix header states that each row is a guarantee proven by a live probe the CI conformance/landlock jobs run, and links to those jobs — it does not print PASS/FAIL per row (which would be vacuously green in the committed file). This matches the user's decision and avoids embedding transient state in version control.

5. **Group by spec capability, stable order.**
   Rows are grouped by backing capability and sorted deterministically (by capability, then probe name) so regeneration is stable and diffs are minimal — essential for the drift check to be meaningful.

## Risks / Trade-offs

- [A probe's source phrasing is edited (reworded) → the registry key no longer matches → lint fails] → Intended: a reworded probe is a real change the matrix must reflect; the failing lint names the unmatched probe, and updating the registry key is a one-line fix. This is the drift check doing its job.
- [The matrix shows coverage, not live pass/fail, so a reader might over-read "listed" as "passing right now"] → Mitigated by the header wording (proven by CI jobs X/Y, linked) and by the fact that a red CI blocks merges anyway.
- [Parsing source with regex is brittle to exotic formatting] → The probe/check declarations are single-line, uniform literals; the parser is line-oriented and unit-tested, and the cross-check catches any missed line (it would show as an unmapped/again-missing probe).

## Migration Plan

Additive: a new generator, a generated doc, a README pointer, and one more doc-lint invariant. No config/runtime/spec change. Rollback is deleting the files and the lint block. Ships in the next release (or rides `[Unreleased]` as a docs/tooling change).
