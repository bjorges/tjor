# Proposal

## Why

ADR 0010 (#6) established discovered-secret scrubbing design-first — a conservative known-shape detector (`python/tjor_secrets.py`) wired into one low-risk sink (the denial log) as proof — and deliberately deferred the **highest-yield boundary**: the egress inference / gateway request body, where a secret the agent read from repo content or tool output and pasted into a prompt would leave the session. #62 tracks that boundary, and its acceptance is design-first: *pick the mechanism, the match→action contract, and the evasion/latency stance in an ADR; only then implement behind it.*

The decisive framing (ADR 0010, and confirmed for this change): body scanning **cannot be a guarantee**. The agent can trivially evade it — base64, split across messages, any encoding — and it is the agent's own outbound request. So the honest mechanism is a **best-effort tripwire for _accidental_ verbatim leakage**, not data-loss prevention against a hostile agent. And the exfiltration-conscious-profile work already recorded that content entering the model context reaches every allowed egress destination *by design* — so the tripwire observes, it does not (and cannot) seal that path.

## What Changes

- **ADR 0011** (`docs/decisions/0011-egress-secret-tripwire.md`, building on 0010): records the decision — an **observe-only tripwire** on outbound inference request bodies, scoped, bounded, fail-safe; the match→action contract (**signal, never alter or block**); the evasion stance (best-effort against accidental leaks, explicitly **not** a guarantee); the latency stance (bounded scan); and that enforcement (redact/block) stays deferred pending real signal and an understood correctness/latency cost.
- **The tripwire (the proof)**: the proxy scans the request body of allowed requests to a configured **inference host** (the gateway host when the D4 gateway is enabled, plus any host listed in a new `[secrets] scan_hosts`) for known secret *shapes* using the existing detector, up to a bounded byte cap, and **forwards the request unchanged**. On a match it records a per-session signal — a count and the secret *kinds* matched (never the secret value, never the body) — surfaced in the `tjor down` recap alongside the denial recap. Fully fail-safe: a scan error never alters, blocks, or delays the request.
- **A `kinds_present(text)` helper** in `tjor_secrets.py` (total, like `redact`/`contains_secret`): returns the matched kinds without the values, so the signal can name *what* leaked-shape was seen without re-logging the secret (the #6 concern).
- **Config + wiring**: `[secrets] scan_hosts` (+ `scan_max_bytes`) in `config/tjor.toml`, exported by `bin/tjor` as `TJOR_SECRET_SCAN_HOSTS` / `TJOR_SECRET_SCAN_MAX_BYTES` (auto-including the gateway host when enabled); a bind-mounted per-session signal file, mirroring the #50 log-volume counter.

## Capabilities

### Modified Capabilities

(none — design-first like #6, its parent. ADR 0011 is the durable record; the tripwire is explicitly best-effort and evadable, so a spec *requirement* would overclaim its contract. `.openspec.yaml` sets `skip_specs: true`. #62 closes with the mechanism chosen + a working proof; enforcement stays a deferred, separately-decidable step.)

## Impact

- **Code**: `python/tjor_secrets.py` (`kinds_present`); `proxy/addon.py` (scan the body of allowed requests to a scan-host in the `request` hook — observe-only, bounded, in its own swallow-all guard so it can never trip the hook's fail-closed deny path); `config/tjor.toml` (`[secrets] scan_hosts`, `scan_max_bytes`); `bin/tjor` (export the knobs, auto-add the gateway host, pre-create the signal file); `compose.yaml` (bind-mount + env for the signal file, mirroring the denial/log-volume files).
- **Docs**: `docs/decisions/0011-egress-secret-tripwire.md`.
- **Tests**: `python/tests/` (detector `kinds_present`; the addon scans only scan-hosts, records count+kinds not the value, forwards the body byte-for-byte unchanged, is bounded, and is fail-safe — a scan error never denies/alters); a `tjor down` recap aggregation test.
- **Behavior change**: `tjor down` gains a best-effort line when a session sent inference bodies containing known secret shapes; the request itself is never altered, blocked, or delayed; no egress-boundary, policy, or credential change. Closes #62 with an honest, non-overclaiming tripwire; enforcement deferred.
