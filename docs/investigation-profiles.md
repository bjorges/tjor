# Exfiltration-conscious investigation profiles

A read-only Kubernetes investigation session usually wants `pods/log` — the
single most useful read verb, and the single most likely to pull sensitive
customer data (PII, accidentally-logged secrets, tokens in stack traces) into
an LLM context. **Reading is the point; the question is where that content can
go afterwards.** This guide is the checklist tjor's other mechanisms hang off
when a profile grants log access (#50).

The honest premise first: once content is read into the session, it reaches
**every remaining allowed egress destination by design** — including the
inference endpoint, because talking to a model is why the session exists — and
it appears in the human-visible transcript. No egress control can un-read it.
What tjor *can* do is make the set of possible sinks exactly the set you chose
on purpose, and show you every attempt to reach anything else.

## The checklist

Work top-down; the first item does most of the work.

1. **Strict-allow egress with nowhere to put content.** Give the profile its
   own trusted `.tjor/policy.toml` in `strict-allow` mode, allowing ONLY:
   - the cluster API server host (tjor prints the exact `tjor policy add` line
     at launch; injection itself is already scoped to the API server's exact
     `host:port` origin, #49, and the host is exempted from the SSRF guard
     without a global opt-out, #45);
   - the inference path — the LLM gateway host when you run one (D4
     concentrates all model traffic onto a single internal host), else the one
     provider API host.

   Nothing else. In particular no code-hosting, paste, artifact, chat-webhook,
   or object-storage hosts: every extra allowed host is a possible sink for
   log content. An investigation session rarely needs to fetch anything.

2. **RBAC is the read policy — keep `secrets` out of it.** Bind the session's
   ServiceAccount to a view-level Role that **excludes `secrets` get/list**
   and names `pods/log` explicitly, so the grant is visible in review rather
   than inherited silently from `view`. A mutating attempt is rejected by the
   cluster, by construction.

3. **Short token TTL.** `kube_duration` as short as the investigation allows
   (there is no in-cage refresh; a session outliving the token re-launches —
   that friction is a feature here).

4. **Read the denial recap at teardown.** `tjor down` prints every denied
   egress attempt (count + top hosts, #42). In an investigation session that
   list should be empty or boring; a denied host you don't recognize is a
   signal that something in the session tried to move content somewhere you
   didn't allow. Review it before you widen anything.

5. **Name the trade-off in the profile itself.** Put a comment in the
   profile's policy/config saying log content is expected in-context and the
   allowed sinks are the API server + inference only. Future-you approves that
   file through `tjor trust` — make the choice legible at that moment.

## Worked example

`.tjor/policy.toml` (approve with `tjor trust` after review):

```toml
# Investigation profile: pods/log is granted -> egress is SINKLESS on purpose.
# Log content read into this session can reach ONLY the two hosts below.
mode = "strict-allow"

[hosts]
allow = [
  "api.my-cluster.example",   # the cluster API server (see the launch hint)
]
# Inference: with the LLM gateway (D4) enabled, its internal host is carved in
# automatically and provider keys never enter the cage — nothing to add here.
# Gateway-less setups add exactly one provider host (e.g. api.anthropic.com).
```

`~/.config/tjor/config.toml` (or the same trusted `.tjor/config.toml`):

```toml
[broker]
source = "kube"
kube_sa = "investigate-readonly"   # bound to a view-minus-secrets Role, pods/log named
kube_namespace = "prod"
kube_duration = "30m"
```

Role sketch (cluster-side, not tjor config):

```yaml
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "events", "services", "endpoints"]
    verbs: ["get", "list", "watch"]
  # deliberately NO "secrets" — and pods/log is named, not inherited.
```

## Residual risk — accepted, not mitigated

- The model provider (or your gateway's upstream) **receives whatever log
  content enters the context**. That is the session working as designed.
  Choose the provider/gateway accordingly for the data class involved.
- Log content appears in the session transcript and harness state under the
  session's state root on the host. `tjor reset` tiers exist for cleanup.
- Volume friction (size/rate limits on `pods/log` reads at the proxy) is a
  real open design question, deliberately not implemented yet — thresholds and
  streaming semantics need operator input before it can be specced honestly.
  Status and the current proposal (observability first: a per-session
  log-bytes counter in the teardown recap) are tracked in issue #50.
