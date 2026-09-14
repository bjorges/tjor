## Why

The entrypoint installs the placeholder GitHub git-credential helper whenever ANY broker is enabled, regardless of what the broker actually covers (#47). Under `[broker] source = "kube"`, injection is scoped to the cluster API host only — GitHub is not a brokered destination — yet git/gh still send the literal placeholder to github.com and get 401s, instead of falling back to ambient GitHub auth (`gh auth login`). A deliberate "no GitHub credential in this session" posture looks like broken git setup.

## What Changes

- The placeholder GitHub credential helper is wired only when the broker's destination hosts actually cover GitHub (`github.com`/`gist.github.com`), matched with the shared policy host matcher — never a second matcher. Otherwise the standard `gh` fallback helper is wired, exactly as in a broker-less session.
- `TJOR_BROKER_HOSTS` (hostnames only — no secret) is passed to the agent container so the entrypoint can make that decision.
- `tjor_policy.py` + `tjor_identity.py` ship as agent-image cargo (`/opt/tjor/python/`) so the in-cage decision uses the same glob semantics as the proxy's injection scoping.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `credential-broker`: new requirement — placeholder credential wiring SHALL be scoped to brokered destinations; a broker that does not cover GitHub leaves the ambient GitHub auth path intact.

## Impact

- `compose.yaml` (agent service env), `images/agent/Dockerfile` (python cargo), `images/agent/entrypoint.sh` (helper gating) — requires an agent-image rebuild.
- `tests/integration/broker_test.sh`: entrypoint-driven cases for covered vs kube-only hosts; the existing live placeholder assertions (github-covering pat broker) remain valid.
- Compatibility note: a new image behind an old launcher (no `TJOR_BROKER_HOSTS` in the agent env) resolves to the gh fallback; launcher and image ship together (git checkouts build locally, published images are pinned per release), so this pairing does not occur in supported flows.
