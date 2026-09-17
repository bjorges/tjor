# tjor

> *tjor* (Norwegian, nynorsk): **tether** — the rope that lets an animal graze freely, but only within a safe radius.

tjor runs AI coding agents (Claude Code, opencode, GitHub Copilot CLI) inside a portable, fail-closed container cage with per-session state, identity, lifecycle, and brokered credentials. The agent works at full speed inside the boundary — and the boundary, not the prompt, is the policy. Per-session identity metadata (D1), the session lifecycle UX (D3 — `ls`/`attach`/`gc`/`reset`, named and detached sessions), the credential broker (D2), and an optional LLM gateway (D4) are all shipped — the roadmap deltas are complete.

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
agent can work across several repos at once; `--dir-ro <path>` does the same
**read-only** — enforced at the mount, container-wide, so nothing in the cage
can write, delete, or rename inside that tree (the kernel-sandbox tier grants
it read-only too, when active). Writable mounts are git-trusted as **trees**
(git ≥ 2.46 scoped prefix trust): a worktree or repo the agent creates under
them mid-session, or a repo nested under a mounted parent dir, just works —
trust never extends outside the mounted roots, and never becomes a blanket
`*`. The stated trade-off: that includes vendored repos inside a mounted
repo, so their `.git/config` is trusted too (bounded by the cage, chosen by
the mount). Read-only mounts keep **exact-path** trust: git's
dubious-ownership refusal stays in force for nested repos there — it is what
keeps a hostile pre-existing `.git/config` (fsmonitor, pager, hooks) from
executing in unvetted read-only content. Need git in repos under a `--dir-ro`
parent? Mount the individual repos `--dir-ro`, or mount the parent writable.
`tjor policy <url>` previews an
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

**Granting `pods/log`?** Workload logs are the read most likely to pull
sensitive data into the session — make it a conscious trade-off: follow the
exfiltration-conscious checklist in
[docs/investigation-profiles.md](docs/investigation-profiles.md) (minimal
sinkless egress, view-minus-secrets RBAC, the teardown denial recap).

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

**Definitions, not credentials.** tjor stages only a **structural allow-list**
of definition subdirectories — `agent`/`agents`, `command`/`commands`,
`skill`/`skills`, `prompt`/`prompts`, `mode`/`modes` — host-side, and mounts only
that. So a credential/config file at the profile *root* — an `auth.json`,
`opencode.json`, or API key sitting beside those dirs in `~/.opencode` — is
never copied (verified in CI). As defense in depth, well-known credential
filenames and key/cert extensions (`auth.json`, `id_rsa`, `*.pem`, …) are also
skipped *inside* the definition dirs. What tjor **can't** do is tell a
definition file from a secret by its content — so don't hide a token inside a
definition directory; a profile is instructions the agent runs, so treat it as
trusted content you authored. The staged definitions overlay the image's
baseline instructions (your definitions win on conflict). Because a profile is
*you* naming *your own* directory, the `--profile` selection is the consent — no
separate trust step (unlike a repo's `.tjor/`, which travels with code and needs
`tjor trust`). Content must already be in the active harness's format; tjor
deploys it, it doesn't translate between harnesses.

**Managed opencode config (hardened profiles).** A profile may carry
`managed/opencode.json`. It is deployed **root-owned** to
`/etc/opencode/opencode.json` — opencode's managed-settings path, which loads
after, and cannot be overridden by, any user- or project-level opencode
config — before the privilege drop, so the agent can't write, replace, or
remove it. That makes it the right home for permission policy a hardened
profile must keep even when a mounted repo ships its own `opencode.json` or
agent definitions. A staged managed file that isn't valid JSON refuses the
launch (a profile must never *look* hardened without *being* it); with no
profile, nothing is deployed and any stale managed file is removed. Honest
scope note: managed settings override config *keys*; they don't stop a repo's
project config from *adding* plugins or local MCP servers — that surface is
closed structurally by `mask_dirs = [".opencode"]` above, and hardened
profiles should use both together. This pairing matters more now that
worktree creation is routine (#53): a fresh worktree re-materializes
working-tree content that launch-time `mask_dirs` masking does not cover
(its documented mid-session residual) — the managed tier is the control
that survives tree growth, and a read-only investigation profile
additionally keeps git's ownership barrier for nested content.

## LLM gateway (LiteLLM, D4)

Optionally route the harness through a **LiteLLM gateway** instead of allow-listing
each provider. Off by default; enable it in config:

```toml
[gateway]
enabled = true
provider_key_envs = ["ANTHROPIC_API_KEY"]   # your keys, passed only to the gateway

[[gateway.models]]
name = "claude"
model = "anthropic/claude-sonnet-4-20250514"
api_key = "os.environ/ANTHROPIC_API_KEY"
```

When enabled, a LiteLLM sidecar runs on the **egress** network and the harness's
`base_url` points at it. What the design guarantees:

- **One host, not one-per-provider.** The agent reaches the gateway only through
  the proxy, so the egress policy gains exactly one host (the gateway); LiteLLM
  fans out to your providers from the egress side.
- **Admin surface unreachable by construction.** The proxy — the agent's only
  route to the gateway — allows **only inference paths** toward it (`/v1/chat/completions`,
  `/v1/messages`, …); the entire LiteLLM management API is denied by construction
  (the gateway host is default-denied with the inference paths carved back in),
  not by a password. A new admin route in a future LiteLLM does not open it.
- **The gateway key never enters the agent.** A per-install master key is
  generated (0600, under your config dir — never a session dir, label, or config
  hash) and injected by the proxy toward the gateway host; the agent holds only a
  placeholder. Your provider keys stay on the egress side (gateway sidecar only).

Rotate the generated master key any time with `tjor gateway rotate-key` (new
sessions pick it up; running gateway sessions keep theirs until relaunched).

MVP notes: the gateway targets LiteLLM's OpenAI/Anthropic-compatible endpoints
(so `--harness claude` and OpenAI-style usage work directly; per-harness base_url
specifics are evolving); the LiteLLM image is digest-pinned; secrets reach the
gateway/proxy sidecars as container env (visible via `docker inspect`, within
the docker-socket-trusted threat model — see ADR 0009); a live provider
round-trip is a manual check (CI has no keys). See ADR 0009 and the design under
`openspec/`.

## Kernel sandbox (Landlock, #9)

A defense-in-depth **hardening add-on** (not a core guarantee): inside the cage,
the harness process tree runs under a kernel-enforced [Landlock](https://docs.kernel.org/userspace-api/landlock.html)
allowlist (via [cplt](https://github.com/navikt/cplt), MIT), plus launch-time
masking of in-repo secret files. It narrows what a compromised agent can touch
*within* the container — the container boundary itself is unchanged and remains
the thing tjor relies on.

What it does, in two independent mechanisms:

- **Kernel FS allowlist (Landlock).** The harness and everything it spawns can
  reach only the granted trees (your workspace, any `--dir` repos, its own state,
  and the system paths needed to run). A read or write **outside** those trees is
  denied by the kernel and the restriction is irrevocable for the process tree.
  (Landlock is allowlist-only — it *cannot* subtract a path inside a granted tree,
  which is why in-repo secrets use the second mechanism.)
- **Dotenv masking (mounts, every runtime).** At launch, each `.env` / `.env.*`
  in the mounted repos (templates like `.env.example` excluded) is masked with a
  read-only empty bind mount, so its contents are unreadable in-cage even where
  Landlock is unavailable. A masked file can't be unlinked or replaced by the
  agent. Residual, stated plainly: a dotenv file *created mid-session* is not
  masked — masking is a launch-time snapshot.
- **Directory masking (`mask_dirs`, mounts, every runtime).** The same
  mechanism for whole directories: each configured entry — an absolute path,
  or a bare name like `".opencode"` discovered recursively in every mounted
  repo — is masked with a read-only **empty** bind mount, so it is
  structurally empty in-cage. This is the structural close for project config
  that auto-executes (opencode loads `.opencode/plugins` and
  `.opencode/tools` with full command execution, outside its permission
  matcher): with the directory masked, there is nothing to load, on every
  runtime, regardless of what the repo ships. Off by default (`mask_dirs =
  []`); hardened/read-only investigation profiles should set
  `mask_dirs = [".opencode"]` and pair it with a managed opencode config (see
  Agent profiles). Same honest residual as dotenv masking: a directory
  *created mid-session* is not masked.

Configure under `[landlock]`:

```toml
[landlock]
mode = "auto"          # auto: enforce when the kernel supports it, else degrade LOUDLY
                       # require: unavailable ABORTS the launch (a core guarantee)
                       # off: kernel tier disabled (stated at launch)
mask_dotenv = true     # launch-time dotenv masking (independent of Landlock)
deny_paths = []        # extra files to mask (absolute; only ever ADDS)
mask_dirs = []         # directories to mask structurally: absolute paths or bare
                       # names discovered in every mounted repo (no globs);
                       # independent of mask_dotenv; e.g. [".opencode"]
```

The tier states its status in the agent's startup log, one greppable line:

```
tjor-entrypoint: kernel-sandbox: active (landlock ABI 4)
tjor-entrypoint: kernel-sandbox: INACTIVE — EOPNOTSUPP; sessions run without the kernel FS-deny tier …
tjor-entrypoint: kernel-sandbox: disabled by config (mode=off)
```

Runtime support: works out of the box on a Linux ≥ 5.13 host/VM kernel with
Landlock enabled — including the default Docker Desktop and Ubuntu-VM engines,
verified on kernel 6.8 with Docker's default seccomp profile (no privilege or
seccomp changes needed). Where the kernel can't enforce it (older kernels,
Landlock disabled at boot, gVisor), `auto` degrades loudly and the masks still
apply. The tier never becomes a second network policy — the egress proxy remains
the sole network boundary. See the design under `openspec/`.

## Exit codes

`tjor` distinguishes an ordinary failure from a **security boundary that could
not be established**, so a wrapping script, supervisor, or CI job can fail
closed on the latter specifically instead of parsing stderr:

| Code | Meaning |
|------|---------|
| `0`  | success |
| `1`  | generic failure — usage error, missing runtime, bad flag, feature setup |
| `90` | a required security boundary could not be established, so tjor refused to run the agent |

Code `90` covers both host-side aborts (the internal-only network, egress
proxy, DNS, or session CA could not be established) and in-cage aborts that the
launcher propagates from the agent container (the non-root guarantee, or
`[landlock] mode = "require"` on a runtime without Landlock). A degraded but
still-safe session — e.g. `[landlock] mode = "auto"` where Landlock is
unavailable — exits `0`: the boundary held, only an optional add-on was absent.

## Why

Prompt-level rules are advisory. Harness-level permissions are harness-specific. The only guarantees that hold for *any* harness — including one running with permissions disabled — are structural: what the process can physically reach. tjor's design is corroborated by multiple independent production systems that converged on the same conclusion: restrict the environment, not the agent.

## Design (short version)

A compose-based container cage reproducing production-validated decisions:

- **Internal-only agent network** — no direct egress, by construction.
- **Dual-homed egress proxy** (explicit mode) with a fail-closed host/path allowlist and a DNS sidecar with zone-scoped forwarding.
- **Non-root agent user; writable repo mounts; per-session state roots** — a profile proven to sustain real daily work, hardened in tested increments.
- **Tiered guarantees**: a core that works on any Docker runtime, plus loud-when-absent hardening add-ons — an in-cage [kernel sandbox](#kernel-sandbox-landlock-9) (Landlock + dotenv masking, #9) and AppArmor on runtimes that support it.
- **Session identity (D1, shipped)**: every session carries a frozen identity (`TJOR_SESSION_ID`, `--task` id, harness, repo, worktree) as environment inside the cage and as the vendor-neutral `x-agent-*` schema on the wire (host filesystem paths are trimmed to their basename on the wire) — the proxy strips forged or unknown identity headers toward every host (a session structurally cannot impersonate another) and injects the identity set only toward hosts you list in `identity.inject_hosts` (e.g. your LLM endpoints).
- **Session lifecycle (D3, shipped)**: `ls` (with live boundary re-check), `attach`, `gc`, tiered `reset`, and concurrent named/detached sessions per repo — see the Quickstart above.
- **Credential broker (D2, shipped)**: short-TTL, per-session credentials injected at the proxy toward configured hosts only — the agent holds a placeholder and never possesses the real secret (proven by a container scan in CI). Configure `[broker]` in your tjor config: `source = "github-app"` (App installation token, ~1h, repo-scoped), `source = "pat"` (static token, still kept out of the sandbox), or `source = "kube"` (a short-TTL Kubernetes ServiceAccount token — see [Kubernetes access](#kubernetes-access-kube-broker) below). See ADR 0007.
- **LLM gateway (D4, shipped)** (optional): an off-by-default LiteLLM sidecar on the egress network — the harness points at it, the egress policy gains exactly one host, and it fans out to whatever provider you configure. Its admin surface is unreachable from the agent by construction (the proxy allows only inference paths toward it), and a generated master key is injected by the proxy so it never enters the agent. See [LLM gateway](#llm-gateway-litellm-d4) below and ADR 0009.

All four roadmap deltas (D1–D4) are now shipped.

See [`docs/clean-room-charter.md`](docs/clean-room-charter.md) for the operational lessons this build is grounded in, and the provenance rules it is built under.

## License

[MIT](LICENSE)
