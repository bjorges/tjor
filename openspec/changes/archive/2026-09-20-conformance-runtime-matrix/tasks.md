# Tasks

## 1. Runtime detection + attestation (bin/tjor)

- [x] 1.1 Add a `detect_runtime` helper that classifies the active engine as `linux-engine` / `colima` / `docker-desktop` / `wsl2` / `unknown` from available signals: WSL first (`/proc/version` or `uname -r` contains `microsoft`, or `$WSL_DISTRO_NAME` set), then `docker context show` (`colima`, `desktop-linux`) and `docker info --format '{{.Name}}'` / `'{{.OperatingSystem}}'`. Unrecognized → `unknown` (never mislabel)
- [x] 1.2 In `cmd_conformance`, name the detected runtime in the PASS/FAIL line and print one copy-pasteable attestation line on completion: `conformance-attestation: result=<PASS|FAIL> runtime=<label> probes=<n> date=<YYYY-MM-DD>`, with `<n>` taken from the suite's own summary output (NOT hardcoded — it grows with every hardening increment)

## 2. The conformance-runtime matrix (docs)

- [x] 2.1 Add `docs/conformance-matrix.md`: a row per supported runtime (`linux-engine`, `colima`, `docker-desktop`, `wsl2`) × verification status — CI-automated (cite the conformance job), maintainer-attested (paste the attestation line), or **not verified here** with the reason (no CI test setup / licensing). Include an explicit limitation statement (why Docker Desktop + WSL aren't in CI, and no mac/Windows runner is added) and the one-command attestation instructions
- [x] 2.2 Reference the matrix from the README security/conformance section (next to the boundary matrix pointer)

## 3. Keep it honest (doc-consistency lint)

- [x] 3.1 In `tests/doc_consistency.sh`, add a grep-shaped invariant (same style as the existing checks): `docs/conformance-matrix.md` exists, the README references it, it names every supported runtime (`linux-engine`, `colima`, `docker-desktop`, `wsl2`), and its CI-automated claim is real — the CI workflow actually invokes `bin/tjor conformance`. Fail with a clear message on any gap

## 4. Tests

- [x] 4.1 A focused check of `detect_runtime`'s classification: given representative signals (WSL `/proc/version`, `docker context show` = colima / desktop-linux, a Docker-Desktop `OperatingSystem` string, a plain Linux engine) it returns the expected label, and an unrecognized signal returns `unknown`. Runnable without a live daemon (inject the signal sources)
- [x] 4.2 Verify the new doc-consistency invariant passes with the matrix in place and fails when a runtime row or the README pointer is removed (mirrors how the boundary-matrix check is exercised)

## 5. Changelog + verification

- [x] 5.1 CHANGELOG entry under `[Unreleased]` (Added) describing runtime-stamped conformance + the conformance-runtime matrix + the honest Docker-Desktop/WSL limitation, referencing #13
- [x] 5.2 Run the full local gate — `pytest python/tests/` (if touched), `tests/doc_consistency.sh`, `shellcheck bin/tjor tests/doc_consistency.sh`, and `openspec validate conformance-runtime-matrix` — and verify green
