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

tjor runs AI coding agents inside a portable, fail-closed container cage: an internal-only network, one explicit egress proxy, brokered credentials, a kernel sandbox.

The clean-room charter's thesis, **the environment is the policy**: prompt text is advisory, harness permissions are harness-specific, and only the structural boundary holds for any harness, including one running with its own permission checks disabled.

---
layout: default
title: Why a cage, not a prompt
eyebrow: Premise
---

<div class="grid grid-cols-2 gap-6 h-full">
<div class="tjor-compact">

**A useful coding agent needs three dangerous things**

- a shell, with the ability to run what it writes
- the network, to fetch packages, read docs, call its model
- credentials, to push code, open PRs, read a cluster

**Every rule you give it is advisory**

- prompt text can be argued with, forgotten, or injected over by what the agent reads: repo content, tool output, a pasted issue
- harness permission systems are harness-specific, and can be switched off
- whatever enters the model context reaches every allowed egress destination, by design (ADR 0011)

</div>
<div class="tjor-compact">

**tjor's stance: restrict the environment, not the agent**

- the agent runs **inside** a container cage: opencode, Claude Code or Copilot CLI, unchanged
- what it can reach is decided by **topology and mounts**, not by instructions
- credentials tjor brokers are applied **at the boundary**, never placed inside; what the agent logs into on its own is its own (ADR 0007)
- the guarantees are **probed by an adversarial suite**: in CI on the Linux engine, and by `tjor conformance` on your runtime; every limit is stated plainly

<Plainly proof>
<p>The charter's thesis, reached independently by every production system it draws on: the environment is the policy. See <code>docs/clean-room-charter.md</code>.</p>
</Plainly>

</div>
</div>

---
layout: default
title: Problems and themes
eyebrow: Map
groups:
  - title: Reach
    items:
      - The agent can reach any host
      - Policy has to see the request, not just the host
      - DNS is an egress channel too
      - A policy that can be bent
      - Blocked, and no idea why
  - title: Secrets
    items:
      - The agent holds the secret
      - Letting an agent operate a cluster
      - One LLM endpoint, no admin hole
      - Secrets the agent discovers
  - title: Host
    items:
      - Inside the container is still a lot
      - Git metadata that runs on your host
      - Mounting the wrong directory
      - A task's notes live in another repo
      - The launcher's own tree
  - title: Trust
    items:
      - Config that travels with the repo
      - Your tooling, not your credentials
      - An image you didn't build
  - title: Operate & prove
    items:
      - A launch that behaves the same every time
      - A task-aware start
      - Which session did what
      - Sessions you can find, reattach, and clean up
      - Does it hold on my machine?
---

::header::

<h1>{{ $frontmatter.groups.reduce((n, g) => n + g.items.length, 0) }} problems, {{ $frontmatter.groups.length }} themes</h1>

::default::

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
specs: [cage-network@b36c84fa, egress-policy@b752140c]
adrs: ['0004']
---

::problem::

- A container with default networking has full egress. One `curl` to a paste site exfiltrates the repo.
- `HTTP_PROXY` is a suggestion: a process that ignores it connects directly.
- Capability drops, seccomp and a read-only rootfs do **not** stop egress. Topology does.

::solution::

- The agent container sits on an **internal-only network** the launcher creates. No route off it exists, so bypassing the proxy is not a policy violation, it is impossible.
- A **dual-homed egress proxy** in explicit mode is the only crossing: a fail-closed host and path allowlist, default deny.
- Raw TCP tunnels are disabled, so a `CONNECT` cannot smuggle non-HTTP bytes.
- The proxy's web UI and the gateway's admin API are unreachable from the agent network; sidecar config cannot drift silently.

<Plainly proof>
<p>Conformance probes: "direct egress bypassing the proxy is impossible", "strict-allow default-deny holds for unknown hosts", "raw TCP passthrough is disabled".</p>
</Plainly>

---
layout: default
title: The cage topology
eyebrow: Topology
specs: [cage-network@b36c84fa]
---

<CageTopology />

---
layout: problem
title: Policy has to see the request, not just the host
specs: [cage-network@b36c84fa, egress-policy@b752140c]
adrs: ['0007', '0012']
---

::problem::

- A `CONNECT` tunnel shows the proxy a hostname and nothing else. Path-level rules, credential injection and identity headers all need the request.
- Inside TLS, a vendor endpoint and its admin route look the same.
- Seeing the request is not enough if the verdict comes after the body has gone, or trusts a header the agent wrote.

::solution::

- The proxy **terminates TLS** with a per-session CA that only the cage trusts, so every request is seen in the clear at the boundary and policy applies to the path, not just the host.
- That is what lets the proxy **overwrite a placeholder with a brokered credential**, **strip forged identity headers**, and carve inference paths out of a blocked gateway host.
- The verdict, the denial and every rewrite happen **at the headers stage, before any byte is forwarded**: a denied streamed body is cut off, not delivered and then refused. HTTP/1.1 only, so every body is declared up front. The method is judged there with the path.
- Every request is judged on the **host its connection was opened to** (the `CONNECT` target, which must equal the server name), never on a `Host` header or an absolute-form request target; either naming another host is denied.

<Plainly>
<p>The proxy is the session's most-trusted component (ADR 0007): it holds the CA key and the brokered secrets and sees every body. Residual (ADR 0012): no HTTP/2 inside the cage, so no gRPC; a large or chunked denied upload, or one asking for a <code>100 Continue</code> before its body, sees a closed connection, with the rule in <code>tjor denials</code>.</p>
</Plainly>

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
- With the resolved-address guard on, the proxy **resolves, validates and pins** the upstream address, so an answer that changes between check and connect cannot redirect to an address the guard never judged.
- Resolution is time-bounded and fails closed; a guard denial never discloses the resolved address to the agent.

<Plainly>
<p>The gateway host and configured kube API hosts are exempt from the guard (private endpoints) and connect unpinned; guard-off mode pins nothing. The sidecar mirrors the allowlist; the proxy stays the sole network boundary.</p>
</Plainly>

---
layout: problem
title: A policy that can be bent
specs: [egress-policy@b752140c]
---

::problem::

- Allowlists die by details: a surprising precedence, a `%2e%2e` that escapes a path rule, a `..` that widens a carve-out.
- A corrupt policy file that quietly allows everything is worse than no policy.
- The proxy, the launcher preview and the CLI each evaluating "their own way" means three answers to one question.

::solution::

- **Fixed, tested precedence**: host blocklist → path allow carve-outs → path blocks → default deny → method gate.
- **Fails closed**: a missing, unparseable or invalid policy denies all egress, loudly.
- **One matcher, everywhere**: proxy addon, `tjor policy` and the launcher share one implementation, and a parity corpus in CI asserts identical verdicts, method included.
- **Encoding-aware, asymmetric matching**: encoding can never widen an allow, a block or a method exception; dot-segments cannot escape a carve-out.
- **Read-only hosts**: `[[methods.restrict]]` narrows a host to listed methods, `[[methods.except]]` admits one method on one exact path; the gate runs last and can only deny; protocol switches and override headers are refused on such a host, judged on the same reading of the policy as the verdict.
- Harness vendor endpoints get path-level treatment, not a blanket host allow.

<Plainly>
<p>The gate sees the verb, not what a request does: a <code>POST</code> exception on a GraphQL endpoint admits mutations, listing <code>GET</code> admits neither <code>HEAD</code> nor <code>OPTIONS</code>, and <code>*</code> in a path spans <code>/</code>. Methods are compared byte for byte, at most 32 characters.</p>
</Plainly>

---
layout: problem
title: Blocked, and no idea why
specs: [policy-ergonomics@46a94f79]
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
$ tjor policy https://x/ --method POST  # preview a write on a read-only host
$ tjor down                             # teardown: denial recap
```

- The active policy is layered, most specific first: a **trusted** repo `.tjor/policy.toml` → `~/.config/tjor/policy.toml` → the packaged default.
- The denial log lives in session state and is readable while the session runs. Each rule kind gets its own hint: a `method-block:` line is widened by a `[[methods.except]]` rule, not `tjor policy add`; a `header-block:` line has no exception.

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
- "Don't print your token" is a prompt rule, and prompt rules are advisory.

::solution::

- A **credential broker**: the real credential lives only in the **proxy sidecar**, on the egress side. The agent holds a fixed **placeholder**.
- The proxy overwrites the placeholder only toward the credential's **destination host** (optionally `host:port`); every other host sees none.
- Lifetime by source: a `github-app` token (~1 h, repo-scoped) is **refreshed** in the proxy and **revoked** at proxy shutdown, best-effort; a `pat` is static, kept out of the cage, forgotten at teardown; a `kube` token expires on its own, unrefreshed.
- A broker that cannot provision disables loudly. With one covering GitHub, `git` and `gh` are authenticated at start; otherwise `gh auth login` is the agent's own.

<Plainly proof>
<p>A CI test scans a live agent container for the token value: absent. Precisely (ADR 0007): tjor places no secret inside; the agent can still mint its own via the device flow. Injection is host-scoped, not call-bound.</p>
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

- `source = "kube"`: at launch tjor mints a **short-TTL ServiceAccount token** with _your_ kubeconfig; the proxy injects it toward that cluster's exact API origin **only**; the agent gets a placeholder kubeconfig.
- **RBAC is the boundary**: bound to a read-only Role, the cluster rejects every mutating call, whatever the agent attempts. A Role that grants writes grants them.
- `[[broker.kube_clusters]]`: one context per cluster, each token origin-scoped, provisioned **all-or-nothing**; a pinned API host must match the active context.
- Cluster API hosts are **exempt** from the resolved-address guard and connect unpinned (private control planes); every other host stays guarded.

<Plainly>
<p>No in-cage refresh: a session outliving <code>kube_duration</code> re-launches. Needs host <code>kubectl</code> and the right to mint the SA's token. <code>pods/log</code> is the read most likely to pull secrets in: a documented trade-off.</p>
</Plainly>

---
layout: problem
title: One LLM endpoint, no admin hole
specs: [llm-gateway@37adb449]
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
- The session policy is generated from your base policy by the one parser: every section survives, the inference paths get exceptions for the methods they use, the result is parsed again before it is written, and a base policy that does not parse fails the launch before anything starts.

<Plainly>
<p>Keys reach the gateway and proxy sidecars as container env, visible to <code>docker inspect</code>, inside the docker-socket-trusted threat model (ADR 0009). The gateway host is exempt from the resolved-address guard. A live provider round-trip is a manual check; CI has no keys.</p>
</Plainly>

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

- **Design first** (ADR 0010): a conservative **known-shape detector** (AWS key ids, GitHub, Slack and Google tokens, PEM blocks). No entropy guessing, so SHAs and UUIDs pass untouched. Wired into one tjor-owned sink today, the denial log, as `[redacted:<kind>]`; it rarely fires there, the proof is the wiring.
- **Egress tripwire** (ADR 0011): for hosts listed in `secrets.scan_hosts` (the gateway host when enabled), the first `scan_max_bytes` of an inference body are scanned, **observe-only**. The request is forwarded byte-for-byte; the signal records kinds, never values, and `tjor down` reports it.

<Plainly>
<p>Trivially evadable by a hostile agent, and the recap line says so. Beyond the size cap, or toward unlisted hosts, nothing is scanned. It catches accidents and produces the signal that would justify enforcement, or not.</p>
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

- Compose baseline: `cap_drop: ALL` plus a minimal `cap_add`, `no-new-privileges`, memory and pid limits. AppArmor is detected and announced; its profiles ship in a later release.
- **Landlock**: the harness process tree runs under a kernel allowlist (workspace, `--dir` repos, its state, system paths); outside is denied, irrevocably. Availability is **probed in the enforcement context**, not inferred from a kernel version.
- Landlock cannot subtract inside a granted tree, so **masks** do: `.env*`, `mask_dirs` (e.g. `.opencode`), every repo's `.git/hooks`, `deny_paths`, an opt-in read-only pin of `.git/config`.
- `mode = auto | require | off`; the tier states its status in one greppable line.

<Plainly>
<p>Masking is a launch-time snapshot: anything created mid-session is unmasked. Hook masking stops host hook frameworks in-cage on purpose (<code>mask_git_hooks = false</code> restores them); <code>core.hooksPath</code> bypasses it unless the config pin is on.</p>
</Plainly>

---
layout: problem
title: Git metadata that runs on your host
specs: [git-tamper-detection@0151ca0e]
---

::problem::

- `core.hooksPath`, `fsmonitor`, a filter driver, a `!` alias, an `include.path`, an `ext::` remote or a planted nested repo, written in the cage, executes in **your** git on the next ordinary command.
- A mask can be bypassed by a config key; what cannot be prevented must at least never be silent.

::solution::

- At launch, a **baseline** of every repo under a writable mount: dangerous keys with values, symlink status, worktree pointers, hook hashes, nested repos. Stored outside every mounted path.
- A **check** at harness exit, at `tjor down` and on demand reports every add, change and removal with old and new values. It **fails closed**: an unparseable config or a new spot where the walk stopped is a finding.
- A **pending marker** written before the agent starts survives crashes; `tjor ls` shows unchecked sessions. `--ack <token>` accepts exactly the reviewed state and nothing else; only an explicit per-session `tjor prune --discard-unreviewed` discards it unreviewed, and says so.

<Plainly>
<p>Detection, not prevention: a write fires in host git the moment it lands; this narrows the window, not closes it. Discovery stops <code>git_check_depth</code> levels down (32) or at an unreadable directory, announces each spot, and a repository planted below one is invisible. Keep <code>--ack</code> in human hands.</p>
</Plainly>

---
layout: problem
title: Mounting the wrong directory
specs: [session-launch@45d44f04]
---

::problem::

- A dotfiles repo whose work tree is `$HOME`: launching from `~` would mount your entire home, writable and git-trusted.
- A `core.worktree` planted in a mounted repo redirects the next launch elsewhere. A read-only root nested in a writable one is re-granted. A worktree's `.git` is a pointer to a directory you never named.

::solution::

- **Sensitive paths are refused** as workspace, `--dir` and `--dir-ro`: `/` and system dirs, home and above, `~/.ssh` `~/.aws` `~/.kube` `~/.config`, tjor's own state and config. `--unsafe-dir` is the one override, loud, and it does not cover a sensitive worktree-pointer target.
- The resolved workspace must be the **nearest repository above the launch directory**, cross-checked against git's answer.
- Mount roots of **different writability never nest**; writable mounts are git-trusted as trees, read-only ones exact-path.
- A worktree's common git directory is mounted only with `--allow-worktree-mount` or an explicit `--dir`, validated by git's native layout, never by a plaintext pointer.

---
layout: problem
title: A task's notes live in another repo
specs: [task-notes@e076f334]
adrs: ['0013']
---

::problem::

- Task notes and hand-offs live in a per-task directory inside one big notes repository. Launching from it makes git climb to that repository's root: every task's files mounted, writable, and the code repository no longer the workspace.
- `--dir` every time is friction, and two tasks in one repository still share one session.

::solution::

- **`[task] notes_dir = "~/scratch/tasks/{task}"`** in the user config: `--task <id>` mounts that directory writable at its physical host path, **through the same path as a `--dir`**, so every rule for extra writable roots applies unchanged; `TJOR_TASK_DIR` names it in the cage, one spelling for the checks, the mount and the agent.
- The notes **root** must exist and is never created; below it, one real directory at a time, never through a link, the template checked component by component.
- **Refused, no override: a workspace that is the notes root or contains it** (by filesystem identity along physical paths, never through a link). The table is **user-config only**: a repository cannot name a host path to mount (ADR 0013).
- Task ids become plain lower-case names; with `session_per_task` the session's short name **is** the id (`tjor down --session <id>`, `tjor attach --task <id>`), and ids the resolver would misread are refused.
- A bounded, link-free scan names credential-shaped files; a probe file an isolated throwaway container must see proves the directory is really shared.

<Plainly>
<p>The directory is writable and git-trusted like any <code>--dir</code>; every session with the same task id shares it; what the agent writes there reaches the host notes repository, nested repos, links and secrets included. The bind source is a path for the engine, so a swap after the checks is outside what the launcher sees. The scan is advisory.</p>
</Plainly>

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
specs: [repo-config-trust@bf175f0d]
adrs: ['0013', '0014']
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
- **Approval never extends to a host mount or to the harness's command line**: the `[task]` table (a notes directory tjor mounts writable, a task prompt) and the `[harness]` table (arguments passed to the harness) are user-config only, ignored in a trusted repo config with a warning (ADR 0013, ADR 0014); a typo under either aborts the launch.

---
layout: problem
title: Your tooling, not your credentials
specs: [agent-profiles@7ab80e54]
---

::problem::

- The cage isolates host config by design: your `~/.opencode` agents, commands and skills do not reach it.
- Mounting that directory would also bring the `auth.json` and API keys sitting beside them.
- A repo's own `opencode.json` can override the permission policy a hardened session relies on.

::solution::

- `--profile <name>` / `--profile-dir <path>`: opt in, per launch. Selecting your own directory is the consent.
- A **structural allow-list** of definition subdirectories (`agent`, `command`, `skill`, `prompt`, `mode`) is staged host-side and only the staging area is mounted; credential filenames and key extensions are skipped.
- A profile's `managed/opencode.json` is deployed **root-owned** to opencode's managed-settings path before the privilege drop: it loads last and its keys cannot be overridden by any repo config.

<Plainly>
<p>tjor cannot tell a definition from a secret by content: a profile is instructions the agent runs. Managed settings override keys but do not stop a repo config from adding plugins or local MCP servers; pair them with <code>mask_dirs = [".opencode"]</code>.</p>
</Plainly>

---
layout: problem
title: An image you didn't build
specs: [image-distribution@36f9144e, cage-image@b791d30d]
adrs: ['0008']
---

::problem::

- Pulling a tag trusts the registry and the publish pipeline, not the Dockerfile you audited.
- A baked uid, a self-updating harness or an unpinned download drifts under you.

::solution::

- A **git checkout always builds locally** and never pulls. Installed copies (Homebrew, the nix package, `nix run` too) pull the release's image, **by digest** when pinned; a bare-tag pull prints an integrity notice.
- Every tool download is **SHA256-gated**; CI proves a tampered checksum fails the build. The build context is **deny-by-default**: only listed `COPY` sources enter it, so a state dir or credential beside the Dockerfile stays out unless someone allowlists it.
- Images are **uid-agnostic and multi-arch**; the agent is **non-root** with its uid aligned to yours at start.
- Harness **self-update is disabled**; instructions are **image cargo**, re-deployed on every start in each harness's dialect.

---
layout: section
number: '05'
title: Operate & prove
---

Launches that behave the same every time, sessions as first-class objects, identity on the wire, and evidence instead of claims.

---
layout: problem
title: A launch that behaves the same every time
specs: [session-launch@45d44f04]
---

::problem::

- Two entry points merging different subsets of the config silently drop an override (charter L19).
- A missing host dependency found halfway through a launch; a hardening tier absent without a word.
- Sessions found by parsing container names break the day a name changes.

::solution::

- **One config merge path** for every entry point: packaged default → user → trusted repo config, minus the user-only tables.
- **Host preflight** with clear errors before anything starts (`tjor doctor`); `--dir` and `--dir-ro` roots are each verified before mounting.
- **Tiered guarantees degrade loudly**: a boundary that cannot be established exits 90; an absent add-on is announced and exits 0.
- A **per-session state root** holds everything durable; the launcher derives the identity set for cage and proxy; containers carry **discovery labels**; sessions start detached, PTY allocated at creation.

<Plainly>
<p>"Degraded but safe" is a judgement the launcher makes for you: Landlock in <code>auto</code> mode missing is exit 0. Set <code>mode = require</code> to make it a boundary.</p>
</Plainly>

---
layout: problem
title: A task-aware start
specs: [harness-launch@3487ce8b]
adrs: ['0014']
---

::problem::

- A wrapper that wants the agent to start on a task, with a first message naming it and its notes directory, or with yesterday's conversation continued, hand-builds the harness command after `--`: text spliced into a shell string, and a guess about when to pass `--continue`.
- The splice differs per harness and sits outside what tjor already knows: which harness, what `--task` resolved, whether tjor started a conversation here before.

::solution::

```toml
[harness.claude]
args = ["--model", "opus"]                 # user config only (ADR 0014)
[task]
prompt = "Task {task}. Notes: {task_dir}."
resume = "auto"
```

- **tjor owns the command line** when asked: `args` pass verbatim, before anything tjor adds; an explicit command after `tjor run` is passed as given, nothing added.
- **The prompt is data on every harness**: opencode `--prompt=<text>`, Claude Code `-- <text>`, Copilot CLI `--interactive=<text>`; two placeholders, `{{ }}` for literal braces, a one-word prompt refused whatever the whitespace around it (`claude -- mcp` opens `mcp`).
- **Resume from tjor's own record**, never from the harness's store: `conversation.json` where no container mounts, read as a bounded regular file, refused when a writable root would cover it, by identity where it exists and by a conservative name match where it does not; `--no-resume` forces fresh; `reset sessions` forgets it.
- Built before the notes directory, the first write, the mint and the sidecars: **a refusal creates nothing**. The launch line shows the prompt by its length and tjor's decision.

<Plainly>
<p><code>args</code> are uninspected: a flag that relaxes the harness, selects a conversation or names a subcommand is yours, and <code>resume = "never"</code> only stops what tjor adds. The prompt is in the container's command line (<code>docker inspect</code>). The record says tjor started a conversation, not that the harness kept one, and it can be absent or stale after a crash between container creation and the write, an explicit command, or a conversation switched inside the harness; <code>--no-resume</code> or <code>reset sessions</code> is the remedy. Without <code>session_per_task</code> only the newest conversation can be continued. The coverage check, like every mount, judges a path the engine resolves again: a swap in between is outside what the launcher sees.</p>
</Plainly>

---
layout: problem
title: Which session did what
specs: [session-identity@c542faab]
adrs: ['0004']
---

::problem::

- Several agents share one LLM account and one git identity; audit logs cannot tell them apart.
- A session that can set a header can claim to be another session.
- Host filesystem paths in headers leak your directory layout to every endpoint.

::solution::

- Every session carries a **frozen identity**: `TJOR_SESSION_ID`, task id, harness, repo, worktree, parent session, as environment inside the cage. A task's notes directory (`TJOR_TASK_DIR`) is cage-only: no header is derived from it.
- On the wire, the vendor-neutral `x-agent-*` schema. The proxy **strips forged or unknown identity headers toward every host**, so one session structurally cannot impersonate another.
- The real set is **injected only toward hosts you list** in `identity.inject_hosts`; paths are trimmed to their basename; identity handling fails closed.

---
layout: problem
title: Sessions you can find, reattach, and clean up
specs: [session-lifecycle@fb11e08c, session-launch@45d44f04]
adrs: ['0006']
---

::problem::

- A `docker run --rm` session dies with a dropped terminal.
- Two tasks in one repo collide on one container; cleanup becomes `docker rm` guesswork that also deletes state.
- A tampered network is invisible until something leaks.

::solution::

```console
$ tjor ls                     # all sessions, boundary re-checked
$ tjor ls --state             # state dirs: containers, age, credentials
$ tjor gc --dry-run           # reap what tjor labelled, never state
$ tjor prune --older-than 30d --dry-run   # delete state, explicitly
```

- Containers are **detached and persistent** (`tjor attach`, by session or `--task <id>`, reconnects); a stopped session relaunches without loss. With per-task sessions the short name **is** the task id, and a reference that could mean two sessions is refused, naming both.
- **State persists until you prune it**: one selector, dry-runnable, refused for a session with a container, an unreviewed git-check or a launch in progress.
- `tjor ls` re-verifies each internal-only network and flags a tampered one **DEGRADED**.

<Plainly>
<p>A persistent container lingers until <code>down</code> or <code>gc</code>: a longer compromise window, accepted because the boundary is time-invariant (ADR 0006). <code>prune</code> forgets credentials rather than revoking them, covers only the credential files tjor knows, and never sweeps what it could not read. <code>reset sessions</code> deletes opencode's session database, Copilot CLI's session state and tjor's launch record; Claude Code's transcripts stay, because their directory also holds its memory.</p>
</Plainly>

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
- Adversarial probes cover <Facts kind="probed" /> of <Facts kind="specs" /> capabilities; the rest are held by functional CI tests, not by probes.
- `docs/conformance-matrix.md` says on which runtimes the suite has been run: the Linux engine in CI, Colima by attestation, Docker Desktop and WSL2 not yet.
- **Tiered guarantees**: a core that holds on any Docker runtime, and add-ons that degrade **loudly** when absent. `tjor doctor` reports both.

</div>
<div class="grid grid-cols-2 gap-3 content-start">

<Stat fact="guarantees" label="adversarial guarantees" hint="docs/boundary-matrix.md" />
<Stat fact="checks" label="checks in the suites" hint="conformance · landlock · launcher" />
<Stat fact="specs" label="spec capabilities" hint="openspec/specs/" />
<Stat fact="adrs" label="decision records" hint="docs/decisions/" />

<div class="col-span-2">
<Plainly proof>
<p>These figures are read from the repository at build time, so this deck cannot quote a stale count. Each problem slide links to the spec or ADR that backs it.</p>
</Plainly>
</div>

</div>
</div>

---
layout: end
title: The boundary, not the prompt, is the policy.
---

```console
$ brew install bjorges/tap/tjor      # or: nix profile install github:bjorges/tjor
$ tjor doctor && tjor conformance
$ cd ~/your/project && tjor run
```

Specs in `openspec/`, decisions in `docs/decisions/`, guarantees in `docs/boundary-matrix.md`.
