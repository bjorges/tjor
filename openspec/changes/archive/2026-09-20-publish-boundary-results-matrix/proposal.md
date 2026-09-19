# Proposal

## Why

tjor's boundary is exercised adversarially in two suites — the conformance probes (`images/conformance/probes.py`: egress bypass, DNS fail-closed, encoding/dot-segment carve-out escapes, raw-TCP smuggling, identity forgery, broker leak, admin-surface reachability) and the kernel-sandbox integration test (`tests/integration/landlock_test.sh`: outside-tree read/write denial, dotenv masking, degradation handoff). Their results live only in CI logs and local runs, so the security posture is real but illegible — a reader can't see the guarantees enumerated (#38). Publish a human-readable pass/fail-style matrix, **regenerated from the suites**, that maps each guarantee to the probe that proves it and the spec requirement it backs — turning "the boundary holds" into something you can see listed.

## What Changes

- **A generator** (`python/gen_boundary_matrix.py`, matching the existing `python/gen_corefile.py` convention) parses every adversarial check from the suite **sources** — the `@probe("…")` decorators in `probes.py` and the `check "…"` / `ok "…"` labels in `landlock_test.sh` — and renders a Markdown matrix.
- **A small registry** (in the generator) maps each probe/check to the guarantee it proves, its suite, and the spec capability it backs (`cage-network`, `egress-policy`, `credential-broker`, `kernel-sandbox`, `session-identity`). The generator **cross-checks the registry against the live suite sources**: every probe/check must be mapped, and no registry row may reference a probe that no longer exists — so the matrix can't silently omit or invent guarantees.
- **`docs/boundary-matrix.md`** is the committed, generated output, referenced from the README's security section.
- **A drift check in `tests/doc_consistency.sh`** regenerates the matrix and diffs it against the committed file (and runs the registry↔source cross-check), so a new, renamed, or removed probe fails the lint until the matrix and its mapping are updated. This is what makes it "regenerated from the suites" rather than a hand-maintained doc that rots.
- **Status semantics**: the matrix expresses *coverage* — each guarantee is backed by a live probe that CI already runs green (the `conformance` and `landlock` jobs). It does not embed transient per-run pass/fail (which would be either always-green or drift); the CI jobs remain the live pass/fail signal, and the matrix makes their coverage legible.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

(none — this is tooling + documentation; `.openspec.yaml` sets `skip_specs: true`. The matrix documents guarantees that `cage-network`, `egress-policy`, `credential-broker`, `kernel-sandbox`, and `session-identity` already own and test; no runtime behavior or capability changes.)

## Impact

- **Code**: `python/gen_boundary_matrix.py` (parser + registry + renderer + `--check` mode); `tests/doc_consistency.sh` (new regenerate-and-diff invariant); `python/tests/test_boundary_matrix.py` (unit tests for the parser and the registry↔source cross-check).
- **Docs**: `docs/boundary-matrix.md` (generated), plus a README pointer.
- **Behavior change**: none at runtime. New repo invariant: adding/renaming/removing a conformance probe or a landlock check now requires updating the matrix registry (the drift lint enforces it), the same discipline the shipped/roadmap and investigation-profile lints already impose. Closes #38 (builds on #13).
