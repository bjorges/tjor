# Tasks

## 1. The grant (images/agent/entrypoint.sh)

- [x] 1.1 Add `--allow-read /proc` to the `wrap` array per D1, with a comment giving the mechanism (cplt's `/proc/self` rule covers the first pid only; Bun aborts in a child; #103, navikt/cplt PR 740) and the measured exposure per D2. Verify: in the built image, with the entrypoint's flags and the pinned cplt, a forked child reads `/proc/self/maps`, `opencode --standalone session list` exits 0 with `--network none`, and `/proc/self/root/etc/hostname` is still denied.
- [x] 1.2 Add `--allow-read /etc/opencode` when the directory exists, per D6. Verify: a sentinel key in `/etc/opencode/opencode.json` is listed by `opencode --standalone debug config` under the wrap, and is absent without the grant.

## 2. Proof (tests/integration/landlock_test.sh, python/gen_boundary_matrix.py)

- [x] 2.1 Extend the part A probe per D4: the paired direct/link denials, the stated residuals, `/proc` not writable, the managed-config sentinel (the launch passes `--profile-dir` with a `managed/opencode.json`), opencode v2 in `--standalone` and in service mode (registration, reuse, loopback URL), with every opencode call under `timeout` and its stderr captured to the workspace and printed on failure; the holder process is started with `docker exec -u agent` and the probe waits for its pid; `/etc/hostname` replaces `/etc/shadow` as the outside-tree read (world-readable, so the denial is Landlock's, with a `docker exec` control). After the first `tjor down`, assert no `opencode serve --service` survives on the engine host, relaunch the session with the stale registration and assert a fresh service. Verify, measured where: the suite passes on Colima (arm64, local) against the image built from the branch, and on the Linux CI runner (x86_64) through the strict `landlock` job; the falsification (the 0.23.0 image's cplt flags without the grants: child read denied, both opencode launches aborting, managed sentinel absent; a `--allow-write /proc` mutation letting the own-`comm` write through) was done by hand on Colima with the probe commands, not in CI.
- [x] 2.2 Register every new name in `python/gen_boundary_matrix.py` (adversarial for the denials and the managed config, functional for the controls, residuals and opencode lifecycle) and run `python3 python/gen_boundary_matrix.py`. Verify: `tests/doc_consistency.sh` is clean and `docs/boundary-matrix.md` carries the new rows.
- [x] 2.3 Add the `landlock` job to `.github/workflows/ci.yml` (`needs: agent-image`, `TJOR_LANDLOCK_TEST_STRICT=1`) and the strict mode to the suite (no Landlock or no `opencode` on the image fails). Verify: the job is green on the pull request; the ruleset on `main` lists it by name (`tests/ruleset_consistency.sh`).

## 3. Documentation

- [x] 3.1 README kernel-sandbox section: bullets under the Landlock mechanism stating the `/proc` grant with its measured exposure and bounds per D2, and the managed-config grant per D6. Verify: `tests/doc_consistency.sh` passes.
- [x] 3.2 `docs/decisions/0015-proc-read-inside-the-kernel-tier.md` per D1–D2 (context, decision, consequences, alternatives). Verify: referenced from the kernel-sandbox slide's `adrs:` and accepted by `tests/slides_consistency.sh`.
- [x] 3.3 Kernel-sandbox slide: re-read, add the `/proc` residual sentence to the Plainly box, add `adrs: ['0015']`, update the pin to the value `tests/slides_consistency.sh` prints after the spec sync. Verify: `tests/slides_consistency.sh` and `cd slides && pnpm check` pass.
- [x] 3.4 `CHANGELOG.md`: `### Fixed` entries under `## [Unreleased]` for #103 (mechanism, residual pointer, the `mode = "off"` workaround no longer needed, CI) and for the managed config. Verify: `tests/doc_consistency.sh` passes.

## 4. Gates

- [x] 4.1 Run and report `python -m pytest python/tests -q`, `tests/doc_consistency.sh`, `tests/slides_consistency.sh`, `shellcheck --severity=warning images/agent/entrypoint.sh tests/integration/landlock_test.sh`, `python3 python/gen_boundary_matrix.py`, and the live `tests/integration/landlock_test.sh`; open the pull request and verify its CI (`unit`, `conformance`, `landlock`) is green.

## Workflow follow-up

- Archived on the same branch; the delta (a MODIFIED entry for the granted-trees requirement) was synced into `openspec/specs/kernel-sandbox/spec.md` by hand because the `openspec` CLI was not installed at the time (it is now, via Homebrew), and the slide pin set to the synced file's hash.
