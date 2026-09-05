# tjor

> *tjor* (Norwegian, nynorsk): **tether** — the rope that lets an animal graze freely, but only within a safe radius.

tjor runs AI coding agents (Claude Code, opencode, GitHub Copilot CLI) inside a portable, fail-closed container cage with per-session state, identity, lifecycle, and brokered credentials. The agent works at full speed inside the boundary — and the boundary, not the prompt, is the policy. Per-session identity metadata (D1), the session lifecycle UX (D3 — `ls`/`attach`/`gc`/`reset`, named and detached sessions), and the credential broker (D2) are shipped; an optional LLM gateway (D4) is the remaining delta on the roadmap (below).

**Status: pre-alpha, working skeleton.** The cage core runs: fail-closed egress with an adversarial conformance suite (15/15 probes green), opencode doing real work inside. Specs live in [`openspec/`](openspec/), decisions in [`docs/decisions/`](docs/decisions/).

## Install

```console
$ brew install bjorges/tap/tjor
```

Requires a Docker engine with compose v2 — **Colima**, Docker Desktop, or a
native Linux engine — plus bash ≥ 4.4, python3 ≥ 3.11, git, and openssl (all
but Docker are usually already present). `tjor doctor` checks them and names
anything missing. (No brew? Clone the repo and run `./bin/tjor`.)

## Quickstart

```console
$ tjor doctor                    # host preflight + active policy + guarantee tiers
$ tjor conformance               # adversarial suite: proves the boundary holds on YOUR runtime
$ cd ~/your/project
$ tjor run                       # caged opencode session in this repo
```

On first run an installed tjor pulls a prebuilt agent image (seconds), then
drops you into a caged opencode session. The first time you need a private
repo or a push, authenticate once inside the session: `gh auth login`.

Sessions are per-repo: state (harness auth, history) persists under
`~/.tjor/sessions/<session>/` across container restarts, while the container
holds no durable state (all of it lives in the state root). Containers are
persistent — they survive a dropped terminal so you can reattach — and are
removed by `tjor down` or `tjor gc`, not automatically (see ADR 0006).
`tjor run --harness claude` / `--harness copilot` select other
harnesses (images build on first use). All three are fully wired, not just
installed: each gets the cage's neutral instructions in its own dialect
(opencode `AGENTS.md`, Claude Code `~/.claude/CLAUDE.md`, Copilot CLI
`~/.copilot/copilot-instructions.md`) and has in-session self-update disabled,
so the image-pinned version can't drift. `tjor run --dir <path>` (repeatable)
mounts additional repositories into the session at their host paths, so one
agent can work across several repos at once. `tjor policy <url>` previews an
egress verdict; `tjor down` removes a repo's topology.

Managing sessions (D3):

```console
$ tjor ls                         # every session, with a live boundary re-check
$ tjor run --session review       # a second, isolated session in the same repo
$ tjor attach review              # reattach to a running agent (detach: ctrl-p ctrl-q)
$ tjor gc --dry-run               # what would be reaped (idle containers/networks)
$ tjor reset cache --dry-run      # tiered state wipe: cache | sessions | creds | all
```

`tjor ls` re-verifies each running session's internal-only network and flags a
tampered one as **DEGRADED**. `gc` only ever deletes docker resources it
labelled — never your session state; wiping state is `reset`'s explicit,
tiered, dry-runnable job.

## Egress policy — and growing it

The cage is fail-closed: the agent can only reach hosts on the allow-list, and
a policy that fails to parse denies everything. The default list covers the
common needs (source hosting, package registries, the harness LLM endpoints).
When something you need is blocked, the loop is:

```console
$ tjor denials                   # what got blocked in this session (host + rule)
$ tjor policy add registry.example.com   # add it to your allow-list
$ tjor policy https://x/ --explain       # why a URL is allowed/denied, and which policy decided
```

The active policy is, most-specific first: a **trusted** repo `.tjor/policy.toml`
→ your `~/.config/tjor/policy.toml` → the packaged default.

## Per-repo config (`.tjor/`)

A repo can carry its own tjor config and egress policy so a setup travels with
the code:

```console
$ tjor init                      # scaffold .tjor/policy.toml + .tjor/config.toml
$ tjor trust                     # review and approve them (required before they apply)
```

Because a repo config can widen the boundary (allow a host, set a broker), it
is **honored only after you approve it** with `tjor trust` — pinned by content
hash, so any later edit needs re-approval. An unapproved `.tjor` config is
ignored with a warning.

On first run, an installed copy pulls a prebuilt, uid-agnostic agent image
for its version from GHCR (`ghcr.io/bjorges/tjor-agent-<harness>`) instead of
building locally; if the image can't be pulled (offline, or a dev checkout),
it builds locally as before. `tjor build` always builds locally.

**Trust note:** pulling a tag trusts the registry and the publish pipeline,
where a local build trusts only the audited Dockerfile and its checksummed
downloads. A git checkout therefore *always* builds locally, and a tag pull
prints an integrity notice. For a verified pull, pin the image by digest
(`[images.digests]`); to always build from source, set `[images] publish =
false`. See [ADR 0008](docs/decisions/0008-prebuilt-image-trust.md) and
[INSTALL.md](INSTALL.md).

## Kubernetes access (kube broker)

Let a caged agent operate a cluster **without ever holding a cluster
credential**, and with the cluster's own RBAC — not the prompt — as the action
policy. With `source = "kube"`, at each launch tjor mints a short-TTL
ServiceAccount token on the host (using *your* kubeconfig for cluster auth) and
the proxy injects it as the bearer token toward the API server host only. The
agent gets a placeholder kubeconfig; the real token stays in the proxy sidecar.

```toml
# ~/.config/tjor/config.toml  (or a trusted .tjor/config.toml)
[broker]
source = "kube"
kube_sa = "agent-readonly"     # a ServiceAccount you've bound to a Role
kube_namespace = "dev"
kube_duration = "1h"           # token TTL; no in-cage refresh
# kube_api_host = "https://…"  # optional; else derived from your current context
```

Then allow the API server host in the egress policy — tjor prints the exact
line at launch:

```console
$ tjor policy add api.my-cluster.example.com
```

**RBAC is the boundary.** Bind `kube_sa` to whatever `Role` fits the session
(read-only to debug, a namespaced role for a scoped task); a mutating call the
agent attempts is rejected by the cluster, by construction. Requires `kubectl`
on the host (it does the cluster auth) and that your identity can `create` the
SA's `serviceaccounts/token`. The token is short-lived with no refresh — a
session outliving it re-launches. See the kube-broker design under `openspec/`.

## Agent profiles

The cage isolates from host config by design, so the agents, commands, and
skills you've defined for your harness (e.g. in `~/.opencode`) don't reach a
caged session. **Opt in** to bring them:

```console
$ tjor run --profile-dir ~/.opencode          # ad-hoc: this host dir
$ tjor run --profile mine                      # named, from [profiles] in config
```

```toml
# ~/.config/tjor/config.toml
[profiles]
mine = "~/.opencode"
```

A profile carries **definitions, never credentials**. tjor stages only an
allow-list of definition subdirectories — `agent`/`agents`, `command`/`commands`,
`skill`/`skills`, `prompt`/`prompts`, `mode`/`modes` — host-side, and mounts only
that; an `auth.json` or API key sitting beside them in `~/.opencode` is never
copied and **cannot reach the cage** (verified in CI: a secret placed in the
source appears nowhere in the container). The staged definitions overlay the
image's baseline instructions (your definitions win on conflict). Because a
profile is *you* naming *your own* directory, the `--profile` selection is the
consent — no separate trust step (unlike a repo's `.tjor/`, which travels with
code and needs `tjor trust`). Content must already be in the active harness's
format; tjor deploys it, it doesn't translate between harnesses.

## Why

Prompt-level rules are advisory. Harness-level permissions are harness-specific. The only guarantees that hold for *any* harness — including one running with permissions disabled — are structural: what the process can physically reach. tjor's design is corroborated by multiple independent production systems that converged on the same conclusion: restrict the environment, not the agent.

## Design (short version)

A compose-based container cage reproducing production-validated decisions:

- **Internal-only agent network** — no direct egress, by construction.
- **Dual-homed egress proxy** (explicit mode) with a fail-closed host/path allowlist and a DNS sidecar with zone-scoped forwarding.
- **Non-root agent user; writable repo mounts; per-session state roots** — a profile proven to sustain real daily work, hardened in tested increments.
- **Tiered guarantees**: a core that works on any Docker runtime, plus loud-when-absent hardening add-ons (e.g. AppArmor on runtimes that support it).
- **Session identity (D1, shipped)**: every session carries a frozen identity (`TJOR_SESSION_ID`, `--task` id, harness, repo, worktree) as environment inside the cage and as the vendor-neutral `x-agent-*` schema on the wire (host filesystem paths are trimmed to their basename on the wire) — the proxy strips forged or unknown identity headers toward every host (a session structurally cannot impersonate another) and injects the identity set only toward hosts you list in `identity.inject_hosts` (e.g. your LLM endpoints).
- **Session lifecycle (D3, shipped)**: `ls` (with live boundary re-check), `attach`, `gc`, tiered `reset`, and concurrent named/detached sessions per repo — see the Quickstart above.
- **Credential broker (D2, shipped)**: short-TTL, per-session credentials injected at the proxy toward configured hosts only — the agent holds a placeholder and never possesses the real secret (proven by a container scan in CI). Configure `[broker]` in your tjor config: `source = "github-app"` (App installation token, ~1h, repo-scoped), `source = "pat"` (static token, still kept out of the sandbox), or `source = "kube"` (a short-TTL Kubernetes ServiceAccount token — see [Kubernetes access](#kubernetes-access-kube-broker) below). See ADR 0007.

Remaining roadmap delta — **specced and tracked in issue #4, not yet built**:

| Delta | Design target |
|---|---|
| **D4 — LLM gateway (optional)** | LiteLLM sidecar on the egress network; backend-agnostic. |

See [`docs/clean-room-charter.md`](docs/clean-room-charter.md) for the operational lessons this build is grounded in, and the provenance rules it is built under.

## License

[MIT](LICENSE)
