# ADR 0011 — Egress inference-body secret tripwire (#62)

**Date:** 2026-09-21 · **Status:** accepted

ADR 0010 established discovered-secret scrubbing design-first — a conservative
known-shape detector (`python/tjor_secrets.py`) wired into one low-risk sink (the
denial log) as proof — and deliberately deferred the **highest-yield boundary**:
the egress inference / gateway request body, where a secret the agent read from
repo content or tool output and pasted into a prompt would leave the session.
This ADR decides that boundary's mechanism (#62), as 0010 said a follow-up would.

The decisive fact, stated plainly: scanning the outbound body **cannot be a
guarantee**. It is the agent's own request; a hostile or careless agent can
base64-encode, split across messages, or otherwise transform a secret to slip
past any shape match. And the exfiltration-conscious-profile work already
recorded that content entering the model context reaches every allowed egress
destination *by design*. So the only honest mechanism is a **best-effort tripwire
for _accidental_ verbatim leakage** — one that *observes*, never one that claims
to seal the path. (The v0.18.15 bubblewrap episode is the cautionary twin:
shipping a mechanism whose guarantee doesn't actually hold is worse than not
shipping it. This ADR names its limits up front.)

## Decisions

1. **Observe-only: signal, never alter or block (the match→action contract).**
   For an allowed request to a configured inference host, the proxy scans the
   body for known secret shapes and, on a match, records a per-session signal —
   then forwards the request **byte-for-byte unchanged**. It never redacts,
   blocks, delays, or rate-limits. This is the whole safety story: a false
   positive produces only a benign operator note, so it can never corrupt a
   prompt or break inference — the exact costs that made redact/block the wrong
   default for an evadable boundary. Enforcement (redact-and-forward, or block)
   is deferred until this tripwire produces real signal and the correctness /
   latency cost of *acting* is understood; each is a separately-decidable step.

2. **Scope: configured inference hosts only.** The scan runs only when the
   destination host is in `secrets.scan_hosts` — the D4 gateway host is
   auto-included when the gateway is enabled (it concentrates inference on one
   host), and gateway-less setups list their inference host(s) explicitly. Empty
   ⇒ the proxy scans nothing. This keeps the tripwire off arbitrary egress and
   makes its coverage an explicit, opt-in choice rather than silent partial
   scanning.

3. **Bounded scan (latency stance).** At most `secrets.scan_max_bytes` (default
   256 KiB) of each body is scanned; a body streamed past mitmproxy's
   `stream_large_bodies` is forwarded unscanned. A pasted secret appears near the
   top of a prompt, so a bounded prefix catches the accidental case while keeping
   per-request cost predictable on the inference hot path. Beyond the cap is
   honestly out of scope.

4. **The signal never carries the value or the body.** A hit records only the
   destination host (redacted + escape-sanitized) and the matched *kinds* (our
   own fixed labels, via `kinds_present`) — never the matched substring, never
   the body. Re-logging the secret is the exact leak #6 set out to prevent. The
   `tjor down` recap aggregates a bounded, session-owned file into one honest
   line (count + kinds), and states in that line that it is best-effort and that
   content reaches allowed egress by design.

5. **Fail-safe, and isolated from the fail-closed request hook.** The scan is
   fully self-guarded (`try/except` swallowing everything) inside the request
   hook's allowed branch. That hook fails **closed** (v0.18.9) — an unguarded
   throw there would *deny* the request — so a scan error must be swallowed
   locally and never reach that guard: observe-only must never turn a legitimate
   inference call into a 403. "Fail" here means "forward unscanned."

## Trade-offs / follow-ups

- **Trivially evadable — stated, not glossed.** The recap line itself says so.
  The value is catching accidents and producing the signal that would justify (or
  not) a future enforcement decision — not stopping a determined agent.
- **Bounded + gateway-scoped coverage.** Secrets past the byte cap, in streamed
  bodies, or to an unconfigured host are not scanned. Documented; the cap and the
  host list are configurable.
- **Enforcement remains deferred.** Redact-and-forward and hard-block both carry
  prompt-corruption and hot-path-latency costs that only real tripwire signal
  can justify weighing. This ADR deliberately does not take that step.
- **Not a spec requirement, on purpose.** Wording a best-effort, evadable
  tripwire as a normative spec ("SHALL detect…") would overclaim its contract;
  this ADR is the durable record instead (the change carries `skip_specs`, like
  #6).
