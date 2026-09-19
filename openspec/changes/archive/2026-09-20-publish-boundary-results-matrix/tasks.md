# Tasks

## 1. Generator (python/gen_boundary_matrix.py)

- [x] 1.1 Parse the suite sources: extract every `@probe("…")` name from `images/conformance/probes.py` and every `check "…"` / `ok "…"` label from `tests/integration/landlock_test.sh` (stdlib `re`, line-oriented); verify with a unit test over a fixture/snippet
- [x] 1.2 Add the registry mapping each probe/check name → (guarantee phrasing, suite, backing spec capability), and a cross-check that asserts set-equality between registry keys and the names found in source (unmapped probe OR stale registry entry = hard error with a clear message); verify via unit test
- [x] 1.3 Render the Markdown matrix: grouped by spec capability, deterministically ordered (capability, then probe), with a header stating status = coverage proven by the CI conformance/landlock jobs (linked). Default run writes `docs/boundary-matrix.md`; `--check` regenerates in-memory, runs the cross-check, and exits non-zero with a diff on mismatch; verify both modes in a unit test

## 2. Generate the doc + README pointer

- [x] 2.1 Run the generator to write `docs/boundary-matrix.md`; sanity-check it lists every conformance probe and landlock check, grouped by capability
- [x] 2.2 Add a README security-section pointer to `docs/boundary-matrix.md`; verify the link resolves

## 3. Drift lint (tests/doc_consistency.sh)

- [x] 3.1 Add an invariant that runs `python3 python/gen_boundary_matrix.py --check` (registry↔source cross-check + regenerate-and-diff) and fails with a clear message on drift; verify `tests/doc_consistency.sh` passes with the committed doc and fails when a probe is added without updating the registry (exercise by a temporary edit, then revert)

## 4. Tests

- [x] 4.1 `python/tests/test_boundary_matrix.py`: parser extracts names from sample source; the cross-check flags an unmapped probe and a stale registry entry; `--check` passes against the committed matrix and fails on a simulated drift; the rendered matrix is deterministic (stable across two runs); verify `pytest python/tests/test_boundary_matrix.py` passes

## 5. Docs and changelog

- [x] 5.1 CHANGELOG entry under `[Unreleased]` (Documentation/Added) describing the published, drift-checked boundary matrix, referencing #38 (and #13)

## 6. Full verification

- [x] 6.1 Run the full local gate — `pytest python/tests/`, `tests/doc_consistency.sh` — and verify everything is green; confirm `openspec validate publish-boundary-results-matrix` passes (skip_specs change)
