# Proposal

## Why

The adversarial conformance suite (#13) is built — 18 probes that actively attempt what the charter forbids (direct egress, DNS exfil, encoded bypasses, CONNECT, admin-surface, identity forge/inject, broker leak…) and assert every attempt fails. It runs live in CI on the Linux engine on every push and has been verified locally on Colima. But "this is what gives the tiered-guarantee model teeth" (the issue) only holds if we are honest about **which runtimes the boundary has actually been proven on**. Of the four runtimes #13 names, two — **Docker Desktop** and **WSL** — cannot be exercised in this project's CI: GitHub's hosted runners don't provide Docker Desktop (licensing/GUI), and WSL needs a Windows runner we've deliberately chosen not to add (the complexity buys no significant advantage over the Linux-engine coverage we already have). Rather than leave that coverage gap implicit, this change makes conformance-across-runtimes **explicit and drift-checked**: automate and track what we can, and honestly document what we can't — and why — with a way to attest the rest.

## What Changes

- **Runtime-stamped conformance.** `tjor conformance` detects the active container runtime/engine (Linux engine / Colima / Docker Desktop / WSL2-backed / unknown) and names it in the PASS/FAIL line, and prints a copy-pasteable **attestation line** (runtime, result, probe count, date) so anyone who runs the suite on a runtime CI can't reach here can record a verifiable result.
- **A tracked conformance-runtime matrix** (`docs/conformance-matrix.md`): each supported runtime × how it is verified — CI-automated (Linux engine), maintainer-attested (Colima), or **not verified here, with the reason** (Docker Desktop and WSL: no CI test setup / licensing). Mirrors the boundary matrix (#38): a single honest source of "where the cage boundary has been proven".
- **A doc-consistency lint** keeps it from drifting: the matrix exists, is referenced from the README, names every supported runtime, and its CI-automated claim matches what CI actually runs (the conformance job on the Linux engine).
- **Honest limitation docs.** The matrix states plainly that Docker Desktop and WSL are not exercised in this project's CI, why, and how a maintainer with that runtime attests them.
- **No new CI runners** (per the decision): automation stays on the existing Linux-engine conformance job; no mac/Windows runner is added.

## Capabilities

### Modified Capabilities

(none — pure tooling + docs, mirroring #38. `.openspec.yaml` sets `skip_specs: true`. The conformance suite already owns and tests the cage boundaries; this change records *where* that boundary has been verified and makes the gaps honest. No product/runtime behavior or capability changes.)

## Impact

- **Code**: `bin/tjor` (runtime/engine detection; the conformance PASS/FAIL line gains a runtime label; a copy-pasteable attestation line on completion). `tests/doc_consistency.sh` (matrix present + referenced + names every supported runtime + CI-automated claim agrees with the conformance job).
- **Docs**: `docs/conformance-matrix.md` (new — the runtime coverage matrix + the honest limitation statement + how to attest); `README.md` (reference it from the security/conformance section).
- **Tests**: `doc_consistency.sh` covers the matrix; a focused check of the runtime detector's classification (given known `docker context`/`docker info` inputs → expected runtime label).
- **Behavior change**: `tjor conformance` output gains a runtime label and an attestation line; nothing else changes — no probe, boundary, policy, or product behavior. Closes the last open item on #13 by making runtime coverage explicit and drift-checked rather than assumed, within the runtimes we can actually reach.
