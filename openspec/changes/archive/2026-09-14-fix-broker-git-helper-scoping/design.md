## Context

See proposal.md — Why. Mechanics that shape the approach:

- The entrypoint's branch is `TJOR_BROKER_ENABLED` alone; compose passes that flag to the agent but NOT `TJOR_BROKER_HOSTS` (which lives egress-side on the proxy). Hostnames are not secret — the agent observes injection targets behaviorally anyway.
- The proxy scopes injection with `tjor_identity.parse_inject_hosts` + `should_inject`, which delegate to `tjor_policy.host_matches` (glob semantics: `*` spans dots; charter — ONE matcher). The agent image ships only `tjor_kube.py` as python cargo today.

## Goals / Non-Goals

**Goals:**
- The in-cage helper decision uses byte-identical matcher semantics to the proxy's injection scoping.
- Kube-only (and any non-GitHub) broker sessions behave exactly like broker-less sessions for GitHub auth.

**Non-Goals:**
- Generalizing placeholder helpers to arbitrary brokered git hosts (GitHub/gist is the only wired pair today).
- Any change to what the proxy injects or how hosts are configured.

## Decisions

1. **Decide in the entrypoint with the shared matcher, shipped as image cargo** (`tjor_policy.py` + `tjor_identity.py` copied to `/opt/tjor/python/`, like `tjor_kube.py`) — rather than re-implementing a glob match in bash (a second matcher, charter violation and drift risk) or deciding launcher-side and passing a boolean (the launcher already passes the hosts to the proxy; passing a derived boolean adds a second source of truth that can disagree with what the proxy actually does).
2. **Coverage = `should_inject(hosts, "github.com") or should_inject(hosts, "gist.github.com")`.** The helper pair is wired/skipped atomically — same condition the proxy would use to substitute toward those hosts.
3. **Empty/missing `TJOR_BROKER_HOSTS` with an enabled broker → gh fallback.** Matches the proxy, which only activates injection when hosts are non-empty; a placeholder no one substitutes is worse than ambient auth.

## Risks / Trade-offs

- [New image with an old launcher lacks the env and falls back to gh even for a GitHub broker] → launcher+image ship together (git checkout builds locally; published images pinned per release). Noted in the proposal.
- [Python import cost at container start] → one short-lived `python3` invocation; the entrypoint already runs several.

## Migration Plan

Agent-image rebuild required (Dockerfile cargo). No config or state migration; rollback is reverting the commit and rebuilding.

## Open Questions

None.
