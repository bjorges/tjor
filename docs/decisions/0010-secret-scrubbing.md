# ADR 0010 — Discovered-secret scrubbing (#6)

**Date:** 2026-09-20 · **Status:** accepted

tjor's credential broker (D2) and gateway (D4) protect secrets the *platform*
issues: the agent never holds them, so it cannot leak them. A distinct risk
class (charter "discovered-secret", issue #6) is untouched by those: a secret
that **already exists** — committed in repo content, printed by a tool, pasted
into an issue — is read by the agent, quoted, and then **persisted** (a summary,
a memory file, a log) or **sent onward**. tjor never issued it, so nothing in
the cage boundary applies. This is a real open design item ("no mechanism
chosen yet") and a known production-incident class for peer systems.

The temptation is to reach straight for data-loss prevention on the egress
inference stream — the highest-yield boundary. We deliberately do **not**, this
increment. Scanning the inference stream is a large surface, trivially evadable
(base64, splitting, encoding), can corrupt legitimate agent work by mangling a
prompt, and sits on a latency-sensitive hot path. Committing that mechanism
before the risk framing and the false-positive stance are settled would over-fix
a design that is still open. This increment is **design-first**: fix the framing
here, ship a small reusable detector, and prove the wiring in one low-risk,
tjor-owned sink — leaving the high-yield boundaries as explicit, ticketed
follow-ups.

## Decisions

1. **Design-first: this ADR is the deliverable, not a capability spec.** #6
   states no mechanism is chosen. A capability spec now would freeze a design
   still open; instead the durable record is this ADR (risk model, boundaries,
   detection stance, deferrals) plus a tested detector and one proof wiring. The
   change carries `skip_specs: true`. A real spec follows when a specific
   boundary is chosen in a follow-up.

2. **Three boundaries mapped; only the safe one is wired now.**
   - **tjor-persisted output / logs [IN, this increment].** Content tjor itself
     writes and later shows a human — the session denial log is the first
     instance. Bounded, tjor-owned, and safe: redacting here cannot corrupt the
     agent's work, only tjor's own record. This is where the mechanism is proven
     end-to-end.
   - **Egress inference / gateway request bodies [DEFERRED — ticketed].** The
     highest-yield boundary and the hardest: the proxy MITMs TLS so it *could*
     scan bodies, but doing so is a full DLP problem — evasion-prone, able to
     corrupt legitimate prompts, and on the latency hot path. It needs its own
     careful design, **not** a drop-in of this detector. See the caution below.
   - **Harness's own memory / summary files [DEFERRED — ticketed].** The agent's
     working files (its persisted memory, session summaries) are a plausible
     persistence sink, but they are the agent's own workspace; scrubbing them
     risks silently corrupting the harness's state and needs the harness's
     cooperation to do safely.

3. **Conservative, known-shape detection — no entropy.** The detector
   (`python/tjor_secrets.py`, stdlib-only) matches only **provably-secret
   shapes**: AWS access-key ids (`AKIA`/`ASIA` + 16), GitHub tokens
   (`ghp_`/`gho_`/`ghs_`/`ghr_` and `github_pat_…`), Slack tokens
   (`xox[baprs]-…`), Google API keys (`AIza…`), and PEM private-key blocks
   (whole `BEGIN…END PRIVATE KEY` block). It deliberately does **not** flag
   high-entropy strings, so UUIDs, git SHAs, base64 blobs, and ordinary prose
   pass through unchanged. A false positive in a security tool erodes trust and
   can corrupt output, so the bias is toward under-matching; new shapes are
   added here on purpose, never guessed by entropy. Entropy/ML detection is a
   considered but rejected option for now, revisitable per boundary.

4. **Legible placeholder.** A match becomes `[redacted:<kind>]` (e.g.
   `[redacted:aws-access-key-id]`) so a reader sees that a secret was present,
   and of what kind, without the value. The placeholder strings are stable and
   unit-tested. `redact()` is total and fail-safe — it never raises, so a call
   site can wrap attacker-influenced content without a new failure mode.

5. **Proof sink = the session denial log; honest about its yield.**
   `_log_denial` in `proxy/addon.py` runs `redact()` over the attacker-influenced
   content it records before `_safe_ascii` sanitizes control bytes. A denied
   *hostname* rarely carries a secret, so in practice this fires seldom — it is
   chosen precisely because it is the single low-risk, tjor-owned sink that
   proves the detector is wired and testable end-to-end (a planted secret in a
   recorded value is redacted on disk). This increment establishes the
   mechanism, not full coverage.

6. **Ship the detector in the proxy image.** `python/tjor_secrets.py` is added
   to the proxy Dockerfile `COPY`, alongside the other `python/tjor_*.py` the
   image already bundles, so the addon's `import tjor_secrets` resolves at
   runtime. Pure stdlib — no new dependency.

## Trade-offs / follow-ups

- **The proof sink rarely fires, so this increment looks thin — accepted and
  stated.** The durable value is this ADR plus the tested, reusable detector;
  the denial-log wiring proves the pattern. Real impact lands when the deferred
  high-yield sinks are wired.
- **Known-shape detection misses novel or custom secret formats — deliberate.**
  A conservative false-positive/false-negative trade: near-zero false positives
  now, at the cost of not catching bespoke shapes. Expanding the pattern set (or
  adding entropy heuristics for a specific boundary) is a considered, deferred
  option, made per boundary.
- **The egress boundary is NOT a drop-in of this detector — explicit caution.**
  A future contributor must not simply call `redact()` on the inference request
  body. That boundary is a separate, careful design: it must reckon with evasion
  (encoding, splitting), the risk of corrupting a legitimate prompt, and hot-path
  latency. This ADR names it as deferred design work, not wiring work.
- **Deferred boundaries are ticketed follow-ups:** (a) egress inference /
  gateway request-body scanning (#62), and (b) the harness's own memory /
  summary files (#63). Each gets its own design when taken up.
