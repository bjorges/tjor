# Conformance runtime matrix

<!-- Authored, not generated (unlike docs/boundary-matrix.md): the rows CI cannot
     reach carry human attestations a generator can't produce. Its structure and
     the CI-automated claim are drift-checked by tests/doc_consistency.sh. -->

Where the adversarial conformance suite (`tjor conformance`, issue #13) has actually been run and passed. The suite proves the cage boundary; this records **on which runtimes that has been demonstrated** — honestly, including the runtimes we cannot reach in this project's CI. Each row is one supported runtime and how its coverage is established.

| Runtime | Status | How it's verified |
|---|---|---|
| `linux-engine` | ✅ CI-automated | The CI `conformance` job runs `bin/tjor conformance` on the Linux engine (`ubuntu-latest`) on **every push** — a red run blocks merge. This is the runtime we automate. |
| `colima` | 🟡 Maintainer-attested | Verified locally on macOS/aarch64. Attestation: `result=PASS runtime=colima probes=18 date=2026-09-14`. |
| `docker-desktop` | 🔴 Not verified here | Docker Desktop cannot run on GitHub-hosted runners (licensing / GUI), so there is no CI path. Attestable by a maintainer who has it (see below). *— not yet attested —* |
| `wsl2` | 🔴 Not verified here | Requires a Windows runner we have deliberately not added: the complexity buys no significant advantage over the Linux-engine coverage above. Attestable manually. *— not yet attested —* |

## Why two runtimes aren't in CI

Honest by design, not an oversight: GitHub's hosted runners do not provide Docker Desktop (it is licensing- and GUI-gated), and WSL needs a Windows runner whose upkeep buys nothing the Linux-engine job doesn't already give us. Rather than add fragile, low-value CI, we **document** the gap and make it **attestable**. The tiered-guarantee model gets its teeth from being honest about where the boundary has been proven — not from a green checkmark that doesn't mean what it appears to.

## How to attest a runtime

On the runtime in question, run the suite and paste its attestation line into the row above, with the date:

```
$ tjor conformance
tjor: conformance PASSED — the boundary holds [runtime=docker-desktop]
tjor: conformance-attestation: result=PASS runtime=docker-desktop probes=18 date=2026-09-20
```

The attestation records the detected runtime, the pass/fail result, the probe count (from the suite's own summary — it grows as probes are added), and the date, so the claim is checkable and visibly ages. A maintainer attestation is trust-based, not a CI proof — that is the honest cost of CI not being able to reach these runtimes.
