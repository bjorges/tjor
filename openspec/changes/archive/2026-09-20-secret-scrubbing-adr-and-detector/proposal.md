# Proposal

## Why

A distinct risk class from credential isolation (#6, charter "discovered-secret"): the agent finds an *already-existing* secret — committed in repo content, printed in tool output — quotes it, and it ends up persisted (a summary, memory, a log) or sent onward. The platform never issued it, so the broker/gateway protections don't touch it. This is a genuine open design item ("no mechanism chosen yet") and a peer-system production-incident class. Rather than commit to a full data-loss-prevention mechanism prematurely — which, at the inference-stream boundary, risks corrupting legitimate agent work and is trivially evadable — this first increment is **design-first**: pick the risk framing and the false-positive stance in an ADR, ship a small reusable detector, and prove the wiring in one low-risk sink, leaving the high-yield boundaries as explicit, ticketed follow-ups.

## What Changes

- **An ADR** (`docs/decisions/0010-secret-scrubbing.md`) records the risk model, the boundaries considered (tjor-persisted output/logs vs the egress inference stream vs the harness's own memory files), why each is or isn't in the first increment, the detection approach (conservative known-shape patterns, **not** entropy, to keep false positives near zero), and what redaction does on a match.
- **A reusable detector** (`python/tjor_secrets.py`, stdlib-only): `redact(text)` replaces known secret shapes (AWS/GCP keys, GitHub/Slack tokens, PEM private-key blocks) with a legible `[redacted:<kind>]` placeholder; `contains_secret(text)`. Conservative by design — it matches provably-secret shapes, not high-entropy strings, so it won't mangle UUIDs, git SHAs, or ordinary prose.
- **One proof-of-concept wiring**: the session denial log (`_log_denial`) passes recorded, attacker-influenced content through `redact()` before it is written — a tjor-owned, low-risk sink that demonstrates the mechanism end-to-end (a planted secret is redacted in the log) without touching the agent's inference stream.
- **The detector ships in the proxy image** (added to the proxy Dockerfile `COPY`), since the addon imports it.
- **Follow-up tickets** for the high-yield boundaries the ADR maps but defers: egress inference/gateway request-body scanning, and the harness's own memory/summary files.

## Capabilities

### Modified Capabilities

(none — design-first: the durable record is the ADR, the deliverable is a detector + proof wiring; no boundary is committed to a capability spec yet. `.openspec.yaml` sets `skip_specs: true`. A real spec follows when a boundary is chosen in a follow-up.)

## Impact

- **Code**: `python/tjor_secrets.py` (detector); `proxy/addon.py` (`_log_denial` redacts via the detector); `images/proxy/Dockerfile` (`COPY` the detector into the image).
- **Docs**: `docs/decisions/0010-secret-scrubbing.md` (the ADR).
- **Tests**: `python/tests/test_secrets.py` (each pattern redacts; false-positive guards — UUID/SHA/prose untouched; PEM block fully redacted; multiple secrets; empty/no-match unchanged); a denial-log test that a planted secret is redacted in the written line.
- **Behavior change**: tjor's denial log now redacts secret-shaped content it records; no change to the inference stream, the agent's files, or the security boundary. Establishes the mechanism for #6; the impactful boundaries are deferred to tickets, deliberately.
