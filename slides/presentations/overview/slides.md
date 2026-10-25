---
theme: default
title: 'tjor: the problems it solves, and how'
titleTemplate: '%s'
info: |
  ## tjor
  Run AI coding agents inside a portable, fail-closed container cage.
  One or more slides per problem; each slide is tagged with the OpenSpec
  capability (`specs:`) and ADRs (`adrs:`) it describes.
colorSchema: dark
fonts:
  sans: Inter
  mono: JetBrains Mono
lineNumbers: false
drawings:
  persist: false
mdc: true
layout: cover
---

**AI coding agents, at full speed, inside a boundary they cannot talk their way out of.**

Prompt rules are advisory. Harness permissions are harness-specific. The only guarantees that hold for _any_ agent are structural: what the process can physically reach.

---
layout: default
title: Why a cage, not a prompt
eyebrow: Premise
---

<div class="grid grid-cols-2 gap-6 h-full">
<div>

**A useful coding agent needs three dangerous things**

- a shell, with the ability to run what it writes
- the network, to fetch packages, read docs, call its model
- credentials, to push code, open PRs, read a cluster

**Every rule you give it is advisory**

- a prompt can be argued with, forgotten, or injected over
- harness permission systems differ per harness, and can be disabled
- the agent is not the adversary you design for; the content it reads is

</div>
<div>

**tjor's stance: restrict the environment, not the agent**

- the agent runs **inside** a container cage — opencode, Claude Code or Copilot CLI, unchanged
- what it can reach is decided by **topology and mounts**, not by instructions
- what it can authenticate as is decided **at the boundary**, never handed inside
- every guarantee is **probed by an adversarial suite** on your runtime, and every limit is stated plainly

<Plainly proof>
<p>A design corroborated by independent production systems that converged on the same conclusion: restrict the environment, not the agent. See <code>docs/clean-room-charter.md</code>.</p>
</Plainly>

</div>
</div>

---
layout: default
title: Eighteen problems, five themes
eyebrow: Map
groups:
  - title: Reach
    items:
      - The agent can reach any host
      - DNS is an egress channel
      - A policy that can be bent
      - Blocked, and no idea why
  - title: Secrets
    items:
      - The agent holds the secret
      - Operating a cluster safely
      - One LLM endpoint, no admin hole
      - Secrets the agent discovers
  - title: Host
    items:
      - Inside the container is still a lot
      - Git metadata that runs on your host
      - Mounting the wrong directory
      - The launcher's own tree
  - title: Trust
    items:
      - Config that travels with the repo
      - Your tooling, not your credentials
      - An image you didn't build
  - title: Operate & prove
    items:
      - Which session did what
      - Sessions you can find and clean up
      - Does it hold on my machine?
---

<ProblemMap :groups="$frontmatter.groups" />

---
layout: section
number: '01'
title: Reach
---

What the agent can talk to. The network boundary is the cage's primary guarantee: everything else assumes it.

---
layout: problem
title: The agent can reach any host
specs: [cage-network@b36c84fa, egress-policy@6f18b695]
adrs: ['0004']
---

::problem::

- A container with default networking has full egress. One `curl` to a paste site exfiltrates the repo.
- `HTTP_PROXY` is a suggestion: a process that ignores it connects directly.
- Capability drops, seccomp and a read-only rootfs do **not** stop egress. Topology does.

::solution::

- The agent container sits on an **internal-only network**. No route off it exists, so bypassing the proxy is not a policy violation, it is impossible.
- A **dual-homed egress proxy** in explicit mode is the only crossing: a fail-closed host and path allowlist, default deny.
- Raw TCP tunnels are disabled, so a `CONNECT` cannot smuggle non-HTTP bytes.
- Sidecar admin surfaces (proxy, DNS, gateway) are unreachable from the agent network; sidecar config cannot drift silently.

<Plainly proof>
<p>Conformance probes: "direct egress bypassing the proxy is impossible", "strict-allow default-deny holds for unknown hosts", "raw TCP passthrough is disabled".</p>
</Plainly>

---
layout: default
title: The cage, as compose builds it
eyebrow: Topology
specs: [cage-network@b36c84fa]
---

<CageTopology />

---
layout: problem
title: DNS is an egress channel too
specs: [cage-network@b36c84fa]
---

::problem::

- With no TCP route, a resolver that forwards every query still leaks: data rides in the labels of `<base64>.attacker.tld`.
- DNS rebinding turns an allowed name into a forbidden address after the policy check.
- A hung resolver on the proxy turns a security boundary into an outage.

::solution::

- A **DNS sidecar** forwards only zones derived from the allow-policy. Every other name is answered **NXDOMAIN locally** and never leaves the cage.
- The proxy **resolves and pins**: it connects only to the addresses it validated, re-evaluated per request, so redirects and rebinding cannot widen scope.
- Resolution is time-bounded and fails closed; a guard denial never discloses the resolved address to the agent.

<Plainly>
<p>The DNS sidecar is not a second policy engine. It mirrors the allowlist; the proxy remains the sole network boundary.</p>
</Plainly>

---
layout: problem
title: A policy that can be bent
specs: [egress-policy@6f18b695]
---

::problem::

- Allowlists die by details: a surprising precedence, a `%2e%2e` that escapes a path rule, a `..` that widens a carve-out.
- A corrupt policy file that quietly allows everything is worse than no policy.
- The proxy, the launcher preview and the CLI each evaluating "their own way" means three answers to one question.

::solution::

- **Fixed, tested precedence**: host blocklist → path allow carve-outs → path blocks → default deny.
- **Fails closed**: a missing, unparseable or invalid policy denies all egress, loudly.
- **One matcher, everywhere**: proxy addon, `tjor policy` and the launcher share one implementation, and a parity corpus in CI asserts identical verdicts.
- **Encoding-aware, asymmetric matching**: encoding can never widen an allow or evade a block; dot-segments cannot escape a carve-out.
- Harness vendor endpoints get path-level treatment, not a blanket host allow.

---
layout: problem
title: Blocked, and no idea why
specs: [policy-ergonomics@1774a891]
---

::problem::

- A fail-closed boundary's first-hour frustration: something is denied, nothing says what or how to fix it.
- The usual response is to widen the policy to `*`, and the boundary is gone.
- A trusted repo policy, a user policy and a packaged default: which one decided?

::solution::

```console
$ tjor denials                          # host + deciding rule, live
$ tjor policy add registry.example.com  # widen by one host
$ tjor policy https://x/ --explain      # verdict, stage, pattern
$ tjor down                             # teardown: denial recap
```

- The active policy is layered, most specific first: a **trusted** repo `.tjor/policy.toml` → `~/.config/tjor/policy.toml` → the packaged default.
- The denial log lives in session state and is readable while the session runs.

---
layout: section
number: '02'
title: Secrets
---

Use, never possess. A credential the agent can read is a credential the content it reads can take.

---
layout: problem
title: The agent holds the secret
specs: [credential-broker@036bd52a]
adrs: ['0007']
---

::problem::

- A GitHub token in the cage is readable by every tool the agent runs, lives as long as the token does, and leaks through `env`, logs or a pasted prompt.
- "Don't print your token" is a prompt rule. See slide 2.

::solution::

- A **credential broker**: the real, short-TTL credential lives only in the **proxy sidecar**, on the egress side. The agent holds a fixed **placeholder**.
- The proxy overwrites the placeholder only toward the credential's **destination host** (optionally `host:port`); any other allowed host sees no credential.
- Refreshed in the proxy, **revoked at teardown**, expiring as the backstop. Fail-closed: a broker that cannot provision disables loudly, never silently downgrades.
- Sources: `github-app` (installation token, ~1 h, repo-scoped), `pat`, `kube`. `git` and `gh` are already authenticated when the session starts.

<Plainly proof>
<p>A CI test scans a live agent container, filesystem, environment and process list, for the token value: absent. ADR 0007 states the gap: injection is host-scoped, not call-bound.</p>
</Plainly>

---
layout: problem
title: Letting an agent operate a cluster
specs: [credential-broker@036bd52a]
---

::problem::

- A kubeconfig in the cage is a cluster credential; "read-only" by instruction is not read-only.
- Several clusters means several credentials, and a token meant for one reaching another.

::solution::

- `[broker] source = "kube"`: at launch tjor mints a **short-TTL ServiceAccount token** with _your_ kubeconfig; the proxy injects it toward that cluster's API origin **only**. The agent gets a placeholder kubeconfig.
- **RBAC is the boundary**: bind the SA to the Role the task needs; a mutating call is rejected by the cluster, by construction.
- `[[broker.kube_clusters]]`: one context per cluster, each token origin-scoped, each API host guarded and pinned, provisioning **all-or-nothing**.
- A pinned API host must match the active context; the kube host is exempt from the SSRF IP guard, deliberately.

<Plainly>
<p>Granting <code>pods/log</code> is the read most likely to pull secrets into the session. It is a documented, conscious trade-off (<code>docs/investigation-profiles.md</code>), and log read volume is observable per session.</p>
</Plainly>

---
layout: problem
title: One LLM endpoint, no admin hole
specs: [llm-gateway@8a0193e8]
adrs: ['0009']
---

::problem::

- Every model provider is another allow-listed host.
- A gateway with a management API inside the agent's reach is a new attack surface, "protected" by a password.
- Provider keys have no business inside the cage.

::solution::

- An optional **LiteLLM sidecar on the egress network**, never on the agent network. The egress policy gains **exactly one host**.
- The proxy allows **only inference paths** toward it; the gateway host is default-denied with those paths carved back in, so the entire management API, including routes LiteLLM adds later, is unreachable by construction.
- A per-install **master key is injected by the proxy** and never enters the agent; provider keys reach the gateway sidecar only. `tjor gateway rotate-key` rotates it.

---
layout: problem
title: Secrets the agent discovers
adrs: ['0010', '0011']
---

::problem::

- The broker and gateway protect secrets the **platform** issues. A secret already in the repo, printed by a tool or pasted into an issue is read by the agent, quoted, then persisted or sent onward.
- tjor never issued it, so no cage boundary applies.
- Scanning the inference stream is a full DLP problem: evadable, prompt-corrupting, on the hot path.

::solution::

- **Design first** (ADR 0010): a conservative **known-shape detector** (AWS key ids, GitHub, Slack and Google tokens, PEM blocks). No entropy guessing, so SHAs and UUIDs pass untouched. Matches become `[redacted:<kind>]` in tjor-owned sinks such as the denial log.
- **Egress tripwire** (ADR 0011): a bounded prefix of inference bodies toward configured hosts is scanned, **observe-only**. The request is forwarded byte-for-byte; the signal records kinds, never values, and `tjor down` reports it.

<Plainly>
<p>Trivially evadable by a hostile agent, and the recap line says so. It catches accidents and produces the signal that would justify enforcement, or not.</p>
</Plainly>

---
layout: section
number: '03'
title: Host
---

What the cage can do to your machine. The network boundary holds; these are the mounts and the files behind it.

---
layout: problem
title: Inside the container is still a lot
specs: [kernel-sandbox@51127809]
---

::problem::

- The container bounds the network; inside it the agent reads every mounted file: the `.env` with production keys, a `.opencode/plugins` dir that auto-executes, every git hook.
- A hardening tier that silently isn't there is worse than none.

::solution::

- **Landlock**: the harness process tree runs under a kernel allowlist (workspace, `--dir` repos, its own state, system paths). Outside is denied by the kernel, irrevocably. Availability is **probed in the enforcement context**, never inferred from a kernel version.
- Landlock cannot subtract inside a granted tree, so **masks** do: `.env*` files, `mask_dirs` (e.g. `.opencode`), every repo's `.git/hooks` by default, `deny_paths`, and an opt-in read-only pin of `.git/config`.
- `mode = auto | require | off`; the tier states its status in one greppable line, in both directions; it is strictly additive to the network boundary.

<Plainly>
<p>Masking is a launch-time snapshot: a dotenv file, directory or repo created mid-session is not masked. <code>tjor git-check</code> covers the rest.</p>
</Plainly>

---
layout: problem
title: Git metadata that runs on your host
specs: [git-tamper-detection@2d035d89]
---

::problem::

- `core.hooksPath`, `fsmonitor`, a filter driver, a `!` alias, an `include.path`, an `ext::` remote or a planted nested repo, written in the cage, executes in **your** git on the next ordinary command.
- A mask can be bypassed by a config key; what cannot be prevented must at least never be silent.

::solution::

- At launch, a **baseline** of every repo under a writable mount: dangerous keys with values, symlink status, worktree pointers, hook hashes, nested repos. Stored outside every mounted path.
- A **check** at harness exit, at `tjor down` and on demand reports every add, change and removal with old and new values. It **fails closed**: an unparseable config or a new spot where the walk stopped is a finding.
- A **pending marker** written before the agent starts survives crashes; `tjor ls` shows unchecked sessions. `--ack <token>` accepts exactly the reviewed state and nothing else.

<Plainly>
<p>Detection, not prevention: a write fires in host git the moment it lands. This narrows the window; it does not close it. Keep <code>--ack</code> in human hands.</p>
</Plainly>

---
layout: problem
title: Mounting the wrong directory
specs: [session-launch@a38b1ce7]
---

::problem::

- A dotfiles repo whose work tree is `$HOME`: launching from `~` would mount your entire home, writable and git-trusted.
- A `core.worktree` planted in a mounted repo redirects the next launch elsewhere. A read-only root nested in a writable one is re-granted. A worktree's `.git` is a pointer to a directory you never named.

::solution::

- **Sensitive paths are refused** as workspace, `--dir` and `--dir-ro`: `/` and system dirs, home and above, `~/.ssh` `~/.aws` `~/.kube` `~/.config`, tjor's own state and config. `--unsafe-dir` is the one override, and it is loud.
- The resolved workspace must be the **nearest repository above the launch directory**, cross-checked against git's answer.
- Mount roots of **different writability never nest**; writable mounts are git-trusted as trees, read-only ones exact-path.
- A worktree's common git directory is mounted only with `--allow-worktree-mount` or an explicit `--dir`, validated by git's native layout, never by a plaintext pointer.

---
layout: problem
title: The launcher's own tree
specs: [launcher-integrity@a945b515]
---

::problem::

- `bin/tjor` runs unsandboxed on the host and is the build context of every image. A session that can write that tree rewrites the next launch.
- "Develop tjor inside tjor" is exactly the case where this bites.

::solution::

- The running tree is **never mounted writable**: as the workspace, a parent of it, or a directory inside it. Refused before any image is resolved or container exists. Read-only is allowed and announced.
- `tjor self-install` produces an **immutable, sha-named copy** of the committed tree under `~/.tjor/install/<sha>`; it still builds locally and never pulls.
- Built images carry `tjor.source-sha`; `tjor doctor` says which kind of tree is running. `--allow-self-mount` overrides, loudly, for disposable setups.

---
layout: section
number: '04'
title: Trust
---

What travels with the code, what you bring from home, and what you did not build yourself.

---
layout: problem
title: Config that travels with the repo
specs: [repo-config-trust@c5f17655]
---

::problem::

- A per-repo `.tjor/policy.toml` is convenient: the setup travels with the code.
- It can also allow a host or set a broker, and a pull request can change it.

::solution::

```console
$ tjor init          # scaffold .tjor/policy.toml + .tjor/config.toml
$ tjor trust         # review, then approve, pinned by content hash
$ tjor trust --show  # review only
```

- A repo config is honored **only after you approve its exact content**. Any later edit makes it untrusted again until re-approved.
- An unapproved config is ignored with a loud warning naming the file and the fix; the session falls back to your user and default config.

---
layout: problem
title: Your tooling, not your credentials
specs: [agent-profiles@7ab80e54]
---

::problem::

- The cage isolates from host config by design, so your `~/.opencode` agents, commands and skills do not reach it.
- Mounting that directory would also bring the `auth.json` and API keys sitting beside them.
- A repo's own `opencode.json` can override the permission policy a hardened session relies on.

::solution::

- `--profile <name>` / `--profile-dir <path>`: opt in, per launch. Selecting your own directory is the consent.
- A **structural allow-list** of definition subdirectories (`agent`, `command`, `skill`, `prompt`, `mode`) is staged host-side; only the staging area is mounted. Credential filenames and key extensions are skipped inside them too.
- A profile's `managed/opencode.json` is deployed **root-owned** to opencode's managed-settings path before the privilege drop: it loads last and cannot be overridden by any repo config. An invalid managed file refuses the launch.

<Plainly>
<p>tjor cannot tell a definition from a secret by its content. A profile is instructions the agent runs: treat it as trusted content you authored.</p>
</Plainly>

---
layout: problem
title: An image you didn't build
specs: [image-distribution@c9dbc811, cage-image@b791d30d]
adrs: ['0008']
---

::problem::

- Pulling a tag trusts the registry and the publish pipeline, not the Dockerfile you audited.
- A baked uid, a self-updating harness or an unpinned download drifts under you.

::solution::

- A **git checkout always builds locally** and never pulls. Installed copies pull the release's image, **by digest** when pinned; a bare-tag pull prints an integrity notice.
- Every tool download is **SHA256-gated**; CI proves a tampered checksum fails the build. The build context is an allowlist, so a state dir or credential can never leak into it.
- Images are **uid-agnostic and multi-arch**; the agent is **non-root** with its uid aligned to yours at start.
- Harness **self-update is disabled**; instructions are **image cargo**, re-deployed on every start in each harness's dialect.

---
layout: section
number: '05'
title: Operate & prove
---

Sessions as first-class objects, identity on the wire, and evidence instead of claims.

---
layout: problem
title: Which session did what
specs: [session-identity@ddbbcf56]
adrs: ['0004']
---

::problem::

- Several agents share one LLM account and one git identity; audit logs cannot tell them apart.
- A session that can set a header can claim to be another session.
- Host filesystem paths in headers leak your directory layout to every endpoint.

::solution::

- Every session carries a **frozen identity**: `TJOR_SESSION_ID`, task id, harness, repo, worktree, parent session, as environment inside the cage.
- On the wire, the vendor-neutral `x-agent-*` schema. The proxy **strips forged or unknown identity headers toward every host**, so one session structurally cannot impersonate another.
- The real set is **injected only toward hosts you list** in `identity.inject_hosts`; paths are trimmed to their basename; identity handling fails closed.

---
layout: problem
title: Sessions you can find, reattach, and clean up
specs: [session-lifecycle@eb604e7d, session-launch@a38b1ce7]
adrs: ['0006']
---

::problem::

- A `docker run --rm` session dies with a dropped terminal.
- Two tasks in one repo collide on one container; cleanup becomes `docker rm` guesswork that also deletes state.
- A tampered network is invisible until something leaks.

::solution::

```console
$ tjor ls                     # all sessions, boundary re-checked
$ tjor run --session review   # a second session, same repo
$ tjor attach review          # reattach (detach: ctrl-p ctrl-q)
$ tjor gc --dry-run           # reap what tjor labelled, never state
$ tjor reset cache --dry-run  # cache | sessions | creds | all
```

- Containers are **detached and persistent**; durable state lives in a **per-session state root** on the host, so a container can be recreated without loss.
- `tjor ls` re-verifies each session's internal-only network and flags a tampered one **DEGRADED**.
- Exit code **90** means a required boundary could not be established, so a wrapper can fail closed without parsing stderr.

---
layout: default
title: Does it hold on my machine?
eyebrow: Proof
---

<div class="grid grid-cols-2 gap-6 h-full">
<div class="tjor-compact">

**A README is a claim; a probe is evidence**

- `tjor conformance` runs the **adversarial suite inside the cage on your runtime** and prints an attestation line.
- `docs/boundary-matrix.md` is **generated from the suites**: every guarantee, the probe that proves it, the spec it backs. A stale matrix or an unmapped probe fails CI.
- `docs/conformance-matrix.md` says on which runtimes it has been proven, and honestly where it has not.
- **Tiered guarantees**: a core that holds on any Docker runtime, and add-ons that degrade **loudly** when absent. `tjor doctor` reports both.

</div>
<div class="grid grid-cols-2 gap-3 content-start">

<Stat fact="guarantees" label="adversarial guarantees" hint="docs/boundary-matrix.md" />
<Stat fact="checks" label="checks in the suites" hint="conformance · landlock · launcher" />
<Stat fact="specs" label="spec capabilities" hint="openspec/specs/" />
<Stat fact="adrs" label="decision records" hint="docs/decisions/" />

<div class="col-span-2">
<Plainly proof>
<p>These figures are read from the repository at build time, so this deck cannot quote a stale count. Each problem slide links to the spec that backs it.</p>
</Plainly>
</div>

</div>
</div>

---
layout: end
title: The boundary, not the prompt, is the policy.
---

```console
$ brew install bjorges/tap/tjor
$ tjor doctor && tjor conformance
$ cd ~/your/project && tjor run
```

Specs in `openspec/`, decisions in `docs/decisions/`, guarantees in `docs/boundary-matrix.md`.
