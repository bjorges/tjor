# Design

## Context

See proposal.md — Why. Grounding in the repo:

- The suite lives in `images/conformance/probes.py` and runs via `tjor conformance` (`cmd_conformance` in `bin/tjor`): it brings up the topology + an echo fixture, runs the probe container, and prints `conformance PASSED — the boundary holds` / `conformance FAILED …` with the run's exit code. The probe count grows with every hardening increment (18 today), so nothing may hardcode it.
- CI runs `./bin/tjor conformance` on `ubuntu-latest` (the Linux engine) on every push — the one runtime we automate. Colima has been verified locally by the maintainer. Docker Desktop and WSL have not been exercised here.
- `bin/tjor` already introspects the engine with `docker info --format '{{…}}'` (e.g. the AppArmor check in `report_tiers`), so a runtime detector has precedent and needs no new dependency.
- `docs/boundary-matrix.md` + `python/gen_boundary_matrix.py` (+ its `--check` in `tests/doc_consistency.sh`) is the drift-checked-doc model. #38 shipped as pure tooling+docs with `skip_specs: true`; this change mirrors it.

## Goals / Non-Goals

**Goals:**
- Make conformance coverage across runtimes **explicit** and drift-checked — automate/track what we can, honestly document what we can't.
- Let anyone with a runtime CI can't reach produce a verifiable attestation with one command.

**Non-Goals (per the decision):**
- No new mac/Windows CI runners — the complexity buys no significant advantage over the Linux-engine coverage we already have, and Docker Desktop can't run on hosted runners at all (licensing/GUI).
- No change to any probe, boundary, policy, or product behavior — this records *where* the boundary was proven, it doesn't change the boundary.
- Not a fully source-generated doc: rows for runtimes CI can't reach carry human attestations a generator can't produce (see Decision 3).

## Decisions

1. **Best-effort runtime detection, conservative — never mislabel.**
   A `detect_runtime` helper classifies the active engine as one of `linux-engine` / `colima` / `docker-desktop` / `wsl2` / `unknown`, from signals already available: WSL first (`/proc/version` or `uname -r` contains `microsoft`, or `$WSL_DISTRO_NAME` is set), then `docker context show` (`colima` → Colima, `desktop-linux` → Docker Desktop) and `docker info --format '{{.Name}}'`/`'{{.OperatingSystem}}'` (a `Docker Desktop` OperatingSystem string, a `colima` name). Anything unrecognized is `unknown` — the detector fails toward an honest "unknown" label rather than a confident wrong one.

2. **A copy-pasteable attestation line on every run.**
   On completion `tjor conformance` prints one machine-and-human-readable line, e.g. `conformance-attestation: result=PASS runtime=docker-desktop probes=18 date=2026-09-20` — the probe count taken from the suite's own summary (not hardcoded, so it can't drift as probes are added). A maintainer who runs the suite on Docker Desktop or WSL pastes this line into the matrix; the runtime label + PASS/FAIL + date make the attestation checkable.

3. **The matrix is human-maintained with a structural lint, not fully generated.**
   `docs/conformance-matrix.md` lists each supported runtime × verification status: `linux-engine` → CI-automated (cites the conformance job), `colima` → maintainer-attested, `docker-desktop` and `wsl2` → **not verified here**, with the reason (no CI test setup / licensing) and the attestation command. Unlike the boundary matrix, the rows CI can't reach carry human attestations a generator cannot produce — so the doc is authored, and a lint (Decision 4) enforces its structure and its automated claims rather than regenerating it.

4. **A doc-consistency invariant keeps the coverage claim honest.**
   `tests/doc_consistency.sh` gains a grep-shaped check (same style as the existing ones): the matrix exists, the README references it, it names every supported runtime (`linux-engine`, `colima`, `docker-desktop`, `wsl2`), and its CI-automated claim is real — i.e. the CI workflow actually runs `bin/tjor conformance`. So the doc can't claim automation that isn't there, and a newly-supported runtime can't be silently dropped.

5. **Honest limitation, stated not implied.**
   The matrix says plainly: Docker Desktop and WSL are not exercised in this project's CI (hosted runners can't provide Docker Desktop; WSL needs a Windows runner we've chosen not to add for no significant gain), and their rows carry the most recent maintainer attestation or `— not yet attested —`. The tiered-guarantee model gets teeth from being honest about this, not from overclaiming.

## Risks / Trade-offs

- [Runtime detection strings vary across versions] → classify conservatively and fall back to `unknown`; the attestation still records a checkable PASS/FAIL, and the label is a convenience, not a guarantee.
- [A maintainer attestation is trust-based, not machine-proven] → accepted and stated: the matrix records the runtime, result, and date of the attestation; it is honest documentation, not a CI proof, exactly because CI can't reach those runtimes.
- [The doc can drift from reality] → the lint enforces structure + the automated claim; the human rows are dated attestations that visibly age.

## Migration Plan

Additive: a runtime detector + attestation line in `bin/tjor`, a new matrix doc, a README pointer, a doc-lint invariant. No config/spec/product change. Rollback is a plain revert. Patch release.

## Open Questions

- None material. If a hosted-runner path to real Docker Desktop or WSL coverage ever appears (e.g. self-hosted runners), the matrix rows flip from attested to automated with no structural change.
