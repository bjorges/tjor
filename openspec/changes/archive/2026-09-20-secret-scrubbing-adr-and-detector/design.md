# Design

## Context

See proposal.md — Why. Grounding in the repo:

- ADRs live in `docs/decisions/NNNN-*.md` (next: `0010`), format `# ADR NNNN — Title` / `**Date:** … · **Status:** …` / `## Decisions`.
- Pure helpers live in `python/tjor_*.py` (stdlib-only); the proxy image ships a subset via the Dockerfile `COPY` (`addon.py`, `tjor_policy.py`, `tjor_identity.py`, `tjor_broker.py`) — a new addon import must be added there.
- `_log_denial(host, rule)` in `proxy/addon.py` writes `safe_host\trule\tts` to the denial log (`tjor denials`), where `safe_host = _safe_ascii(host)`. `host` is attacker-influenced. `_safe_ascii` collapses control bytes; it does not redact secrets.
- The proxy MITMs TLS (so it *could* scan inference bodies) — deliberately out of scope here (see Decisions).

## Goals / Non-Goals

**Goals:**
- Establish the risk framing and a false-positive stance for #6 in a durable ADR.
- Ship a small, reusable, well-tested secret detector.
- Prove the wiring in one low-risk tjor-owned sink, without touching agent work.

**Non-Goals (this increment; deferred to follow-up tickets, named in the ADR):**
- Scanning/redacting the egress inference or gateway request bodies (big DLP surface, evadable, can corrupt legitimate prompts, hot-path cost).
- Touching the harness's own memory/summary files (the agent's working files).
- Entropy-based or ML detection (false-positive-prone); known shapes only for now.
- Committing a boundary to a capability spec (that follows a chosen boundary).

## Decisions

1. **Design-first: an ADR is the deliverable, not a spec.**
   #6 says no mechanism is chosen. Committing a capability spec now would over-fix a design still open. The ADR (`docs/decisions/0010`) records the risk model, the three boundaries (tjor-persisted output/logs, egress stream, harness memory), why the first increment takes only the first (bounded, safe, can't break agent work), and the deferral of the rest. `skip_specs: true`.

2. **Conservative, known-shape detection — no entropy.**
   `redact(text)` matches provably-secret shapes: AWS access-key ids (`AKIA`/`ASIA` + 16), GitHub tokens (`ghp_`/`gho_`/`ghs_`/`ghr_`/`github_pat_…`), Slack (`xox[baprs]-…`), Google API keys (`AIza…`), and PEM private-key blocks (`-----BEGIN … PRIVATE KEY----- … -----END … PRIVATE KEY-----`, whole block). It deliberately does **not** flag high-entropy strings, so UUIDs, git SHAs, and ordinary prose are never mangled — false positives in a security tool erode trust and can corrupt output. The ADR states this stance; new shapes are added deliberately.

3. **Legible placeholder.**
   Matches are replaced with `[redacted:<kind>]` (e.g. `[redacted:aws-access-key-id]`) so a reader of the sink sees that a secret was present and of what kind, without the value. Stable strings (unit-tested).

4. **Proof sink = the denial log; honest about its yield.**
   `_log_denial` runs `redact()` over the content it records before `_safe_ascii`. A denied *hostname* rarely carries a secret, so this rarely fires in practice — it is chosen as the single, low-risk, tjor-owned sink that proves the detector is wired and testable end-to-end (a planted secret in a recorded value is redacted). The ADR is explicit that the high-yield sinks (egress bodies, richer tjor-persisted output, harness memory) are the deferred follow-ups; this increment establishes the mechanism, not full coverage.

5. **Ship the detector in the proxy image.**
   `python/tjor_secrets.py` is added to the proxy Dockerfile `COPY` so `addon.py`'s import resolves at runtime (mirrors the other `python/tjor_*.py` the image already bundles). Pure stdlib — no new dependency.

## Risks / Trade-offs

- [The proof sink (denial log) rarely fires, so the increment looks thin] → Accepted and stated: the durable value is the ADR + the tested detector; the wiring proves the pattern. Impact lands when the deferred high-yield sinks are wired (ticketed).
- [Known-shape detection misses novel/custom secret formats] → Deliberate false-positive/false-negative trade: conservative now; the ADR frames entropy/expansion as a considered, deferred option.
- [A future contributor wires `redact()` into the hot inference path naively] → The ADR explicitly cautions that the egress boundary is a separate, careful design (evasion, prompt-corruption, latency), not a drop-in.

## Migration Plan

Additive: a new pure module, an ADR, one addon call site, a Dockerfile `COPY` line, tests. No config/spec/runtime-contract change beyond the denial log redacting secrets. Proxy image rebuilt per release. Rollback is a plain revert. Patch release.
