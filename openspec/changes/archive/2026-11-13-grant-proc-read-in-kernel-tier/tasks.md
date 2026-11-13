# Tasks

## 1. The grant (images/agent/entrypoint.sh)

- [x] 1.1 Add `--allow-read /proc` to the `wrap` array per D1, with a comment giving the mechanism (cplt's `/proc/self` rule covers the first pid only; Bun aborts in a child; #103, navikt/cplt PR 740) and the residual per D2. Verify: in the built image, with the entrypoint's flags and the pinned cplt, a forked child reads `/proc/self/maps`, `opencode --standalone session list` exits 0 with `--network none`, and `/proc/self/root/etc/hostname` is still denied.

## 2. Proof (tests/integration/landlock_test.sh, python/gen_boundary_matrix.py)

- [x] 2.1 Extend the part A probe per D4: `child_proc_self` (forked `sh -c 'cat /proc/self/maps'`), `opencode_standalone` (`OPENCODE_DISABLE_PROJECT_CONFIG=1 opencode --standalone session list`, `absent` when no `opencode` on PATH) and `proc_root_denied` (`/proc/self/root/etc/hostname`); add the three `check` lines. Verify: `bash tests/integration/landlock_test.sh` on Colima passes with the fixed image and the two positive checks fail against the 0.23.0 image (falsification).
- [x] 2.2 Register the three names in `python/gen_boundary_matrix.py` (functional, functional, adversarial) and run `python3 python/gen_boundary_matrix.py`. Verify: `tests/doc_consistency.sh` is clean and `docs/boundary-matrix.md` carries the new adversarial row.

## 3. Documentation

- [x] 3.1 README kernel-sandbox section: a bullet under the Landlock mechanism stating the `/proc` grant and its residual per D2. Verify: `tests/doc_consistency.sh` passes.
- [x] 3.2 `docs/decisions/0015-proc-read-inside-the-kernel-tier.md` per D1–D2 (context, decision, consequences, alternatives). Verify: referenced from the kernel-sandbox slide's `adrs:` and accepted by `tests/slides_consistency.sh`.
- [x] 3.3 Kernel-sandbox slide: re-read, add the `/proc` residual sentence to the Plainly box, add `adrs: ['0015']`, update the pin to the value `tests/slides_consistency.sh` prints after the spec sync. Verify: `tests/slides_consistency.sh` and `cd slides && pnpm check` pass.
- [x] 3.4 `CHANGELOG.md`: a `### Fixed` entry under `## [Unreleased]` naming #103, the mechanism in one sentence and the residual. Verify: `tests/doc_consistency.sh` passes.

## 4. Gates

- [x] 4.1 Run and report `python -m pytest python/tests -q`, `tests/doc_consistency.sh`, `tests/slides_consistency.sh`, `shellcheck --severity=warning images/agent/entrypoint.sh tests/integration/landlock_test.sh`, `python3 python/gen_boundary_matrix.py`, and the live `tests/integration/landlock_test.sh`; open the pull request and verify its CI (`unit`, `conformance`, `landlock`) is green.

## Workflow follow-up

- Archive the change (`/opsx:archive grant-proc-read-in-kernel-tier`) on the same branch, which syncs the delta into `openspec/specs/kernel-sandbox/spec.md`; then set the slide pin to the synced file's hash.
