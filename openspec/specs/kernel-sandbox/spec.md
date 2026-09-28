# kernel-sandbox Specification

## Purpose

The in-cage kernel filesystem-deny tier: Landlock-backed restrictions on the harness process tree, probed for availability at start, with loud degradation when the runtime cannot enforce them.

## Requirements

### Requirement: Availability is probed in the enforcement context

The cage SHALL determine kernel-sandbox availability by probing Landlock from inside the agent container at start, as the agent user — the same security context that would be enforced. Any probe failure (`ENOSYS`, `EOPNOTSUPP`, `EPERM`, or any other error) SHALL classify the tier as unavailable. Availability SHALL never be inferred from kernel version, runtime name, or host facts.

#### Scenario: Landlock disabled at kernel boot
- **WHEN** the container starts on a kernel where Landlock is compiled in but absent from the boot-time LSM list (probe fails with `EOPNOTSUPP`)
- **THEN** the tier is classified unavailable and the session follows the configured degradation mode

#### Scenario: Hardened seccomp profile filters the syscalls
- **WHEN** the container runs under a custom seccomp profile that denies `landlock_create_ruleset` with `EPERM`
- **THEN** the tier is classified unavailable — the probe result is handled, never crashes startup

#### Scenario: Landlock available
- **WHEN** the probe succeeds and reports a Landlock ABI version
- **THEN** the tier is classified available and (in `auto` or `require` mode) is enforced for the session

### Requirement: The harness runs under kernel filesystem denies when the tier is active

When the tier is active, the harness process and every process it spawns SHALL run under a kernel-enforced allowlist ruleset: filesystem access outside the granted trees (the workspace, operator-mounted extra repos, the harness's own state directories, and system paths needed to run) SHALL be denied by the kernel. The restrictions SHALL be irrevocable for the lifetime of the process tree: no process in the tree can lift or bypass them. (Landlock is allowlist-only — it cannot deny a path *inside* a granted tree; in-tree secret files are covered by the launch-time masking requirement below.)

#### Scenario: Outside-tree read is denied
- **WHEN** the tier is active and the harness attempts to read a container path outside every granted tree
- **THEN** the read fails with a kernel-level denial

#### Scenario: Outside-tree write is denied
- **WHEN** the tier is active and the harness attempts to create or modify a file outside every granted tree
- **THEN** the write fails with a kernel-level denial

#### Scenario: Child processes inherit the restrictions
- **WHEN** the harness spawns a shell or tool that attempts an outside-tree access
- **THEN** the access fails identically — the ruleset is inherited by the whole tree

#### Scenario: Restrictions cannot be dropped in-session
- **WHEN** any process in the harness tree attempts to remove or relax the active ruleset
- **THEN** the restrictions remain in force (the mechanism is one-way for an unprivileged process)

### Requirement: Kernel grants for read-only mounts are read-only

When the kernel-sandbox tier is active, a repository mounted read-only
(`--dir-ro`) SHALL be granted read access but not write access in the kernel
ruleset — the kernel tier and the container-level read-only mount SHALL agree,
so no layer reports the tree as writable.

#### Scenario: Kernel denies writes into a read-only mount

- **WHEN** the tier is active and the harness attempts to write under a
  `--dir-ro` mounted tree
- **THEN** the write is denied, and reads of the same tree succeed

### Requirement: Workspace secret files are masked at launch

Independently of Landlock availability, the launcher SHALL mask dotenv-style secret files (`.env` and `.env.*`, excluding non-secret templates such as `.env.example`) that exist in the mounted repos at session launch, plus every configured extra deny path, by bind-mounting a read-only empty source over each — so their contents are unreadable from anywhere inside the cage, on every runtime. Masking is on by default (`mask_dotenv = true`) and its application SHALL be stated at launch. A mask SHALL NOT be removable or replaceable from inside the cage.

#### Scenario: Masked dotenv read yields no secret
- **WHEN** a `.env` file with secret content exists in the workspace at launch
- **THEN** reading it from inside the cage returns no content, and the secret string appears nowhere in the cage

#### Scenario: Masking holds where Landlock is unavailable
- **WHEN** the kernel tier is unavailable and the session proceeds in `auto` mode
- **THEN** the launch-time masks are still applied and effective

#### Scenario: Mask cannot be removed in-session
- **WHEN** the agent attempts to delete, rename, or overwrite a masked file
- **THEN** the mask remains in place and the secret content stays unreadable

#### Scenario: Mid-session dotenv is not silently claimed
- **WHEN** a new `.env` file is created inside the cage after launch
- **THEN** it is not masked (masks apply at launch), and the documentation states this residual honestly

### Requirement: Tier state is stated loudly, in both directions

At agent start the cage SHALL state the tier's status explicitly and persistently (visible on attach and retained in the container's logs): when active, that the kernel sandbox is enforcing (including the detected ABI version); when unavailable in `auto` mode, exactly which guarantee is inactive and why (the probe's error). A session SHALL never run without the tier while claiming or implying it is active, and SHALL never degrade without stating it.

#### Scenario: Unavailable on a runtime without Landlock
- **WHEN** the tier is unavailable and mode is `auto`
- **THEN** startup continues and a persistent, explicit statement names the kernel-sandbox tier as inactive with the probe's reason

#### Scenario: Active tier is announced
- **WHEN** the tier is active
- **THEN** the startup output states the tier is enforcing and the ABI version detected

#### Scenario: Wrap failure after a passing probe is not silently unwrapped
- **WHEN** the probe classified the tier available but enforcement fails to engage at harness start
- **THEN** the agent does not start unwrapped; startup fails with an explicit error

### Requirement: Operator controls the tier mode through configuration

The tier SHALL be controlled by a `[landlock]` config section flowing through the single config merge path, with `mode` one of: `auto` (default — enforce when available, degrade loudly otherwise), `require` (unavailable aborts the launch before the harness starts), `off` (tier not applied; stated once at start). An unrecognized mode SHALL abort startup with a clear error naming the value.

#### Scenario: require mode on a runtime without Landlock
- **WHEN** mode is `require` and the probe classifies the tier unavailable
- **THEN** startup aborts with an explicit error before the harness process starts

#### Scenario: off mode
- **WHEN** mode is `off`
- **THEN** the harness runs unwrapped and startup states that the kernel-sandbox tier is disabled by configuration

#### Scenario: Invalid mode value
- **WHEN** the merged config contains `mode = "always"` (not a defined value)
- **THEN** startup aborts with an error naming the invalid value

### Requirement: Operator can extend the deny list

The `[landlock]` config SHALL accept additional deny paths (`deny_paths`) that are applied as launch-time masks. Configuration SHALL only extend the default deny set, never weaken it. `deny_paths` SHALL be applied independently of `mask_dotenv`: disabling the automatic dotenv discovery never disables, weakens, or silently drops an explicitly configured deny path.

#### Scenario: Extra deny path enforced
- **WHEN** the config adds a deny path naming a file present at launch
- **THEN** reads of that path from inside the cage return no secret content

#### Scenario: Deny paths survive disabling dotenv masking
- **WHEN** the config sets `mask_dotenv = false` and adds a deny path naming a file present at launch
- **THEN** the deny path is masked at launch (and announced), while automatic dotenv discovery is skipped

### Requirement: Operator can mask directories structurally

The `[landlock]` config SHALL accept a `mask_dirs` list applied as launch-time
directory masks: each entry is either an absolute path (masked directly when a
directory exists there at launch) or a bare directory name containing no path
separator (e.g. `".opencode"`), which SHALL be discovered recursively in every
mounted tree (`.git` internals excluded). Any entry that is neither — a
relative path, an empty string, or a value containing a newline — SHALL abort
the launch with a clear error. A masked directory SHALL appear empty from
anywhere inside the cage on every runtime, its contents SHALL be unreadable
and unlistable, nothing SHALL be creatable inside it, and the mask SHALL NOT
be removable or replaceable from inside the cage. Each applied mask SHALL be
announced at launch with the target path rendered escape-sanitized (directory
names come from untrusted mounted repos). `mask_dirs` SHALL be applied
independently of `mask_dotenv`: disabling automatic dotenv discovery never
disables, weakens, or silently drops a configured directory mask. Directories
created inside the cage after launch are not masked; the documentation SHALL
state this residual honestly. The default is an empty list — masking specific
directories is an operator/profile opt-in.

#### Scenario: Project plugin directory is structurally empty

- **WHEN** `mask_dirs = [".opencode"]` is configured and a mounted repo
  contains `.opencode/plugins/evil.js` at launch
- **THEN** listing `.opencode` from inside the cage shows no entries, the
  plugin file is unreadable at its path, and the launch announced the mask

#### Scenario: Nested occurrences are masked too

- **WHEN** `mask_dirs = [".opencode"]` is configured and a mounted repo
  contains both `./.opencode/` and `./sub/dir/.opencode/` at launch
- **THEN** both directories are masked

#### Scenario: Mask cannot be defeated in-session

- **WHEN** the agent attempts to write into, delete, rename, or remount a
  masked directory
- **THEN** the operation fails and the directory remains empty and read-only

#### Scenario: Directory masks survive disabling dotenv masking

- **WHEN** the config sets `mask_dotenv = false` and `mask_dirs` names a
  directory present at launch
- **THEN** the directory mask is applied (and announced) while automatic
  dotenv discovery is skipped

#### Scenario: Invalid entry aborts

- **WHEN** `mask_dirs` contains a relative path such as `"foo/bar"`
- **THEN** the launch aborts with an error naming the invalid entry

### Requirement: The tier is strictly additive to the existing boundaries

The kernel sandbox SHALL NOT alter the container's security options, network topology, or the harness environment (proxy variables, session CA trust) — and its enforcement mechanism's network proxy and command-guard layers SHALL remain disabled: egress and action policy belong solely to the egress proxy. When the tier is unavailable, every other guarantee SHALL be exactly as strong as before this capability existed.

#### Scenario: Proxied egress unchanged under the wrap
- **WHEN** the tier is active and the harness makes an allowed HTTPS request
- **THEN** the request flows through the egress proxy exactly as without the tier (same proxy env, same session CA trust)

#### Scenario: Degraded session keeps the core boundary
- **WHEN** the tier is unavailable and the session proceeds in `auto` mode
- **THEN** the container boundary, network topology, and proxy policy are byte-for-byte those of a session launched before this capability existed

### Requirement: Git hook directories are masked at launch

By default (`[landlock] mask_git_hooks = true`), the launcher SHALL mask the hooks directory of every git directory it discovers under a **writable** mount root at launch — the workspace repository, each `--dir` repository, repositories nested under a mounted parent, the common git directory of a linked worktree when that directory lies under a writable root, and a writable mount root that is itself a git directory (a worktree's common directory mounted alongside it, whatever its name) — with a read-only empty bind mount, exactly as configured directory masks are applied. A repository whose hooks directory is absent at launch SHALL have an empty one created on the host so the mask has a mountpoint. From inside the cage a masked hooks directory SHALL list empty, nothing SHALL be creatable in it, it SHALL NOT be removable or replaceable, and git SHALL run no hook from it. Each mask SHALL be announced at launch with the path rendered escape-sanitized. Read-only mount roots need no mask and SHALL get none. Setting `mask_git_hooks = false` SHALL disable the mask; the documentation SHALL state that host-installed hooks then fire on in-cage commits again. Documentation SHALL state the residuals honestly: `core.hooksPath` bypasses the hooks mask (the config pin below is the preventive answer); a repository created inside the cage after launch is not masked; sibling repositories under one writable parent are not isolated from each other. A `.git` entry, a hooks directory or a config file that is a symbolic link SHALL be refused at launch and never masked or pinned through (the mask would land on the link's target, a path a previous session could have chosen), regardless of the `mask_git_hooks` and `protect_git_config` settings; the refusal SHALL name the link, its target and the fix. Discovery SHALL NOT descend below a `.git` directory.

#### Scenario: Workspace hooks directory is structurally empty
- **WHEN** the workspace repository has `.git/hooks/pre-commit` at launch
- **THEN** listing `.git/hooks` inside the cage shows no entries, creating a file there fails, and the launch announced the mask

#### Scenario: A host-installed hook does not fire in-cage
- **WHEN** the workspace repository carries a `pre-commit` hook that writes a marker when run, and the agent commits inside the cage
- **THEN** the commit succeeds and the marker is never written

#### Scenario: Nested repository and worktree common directory are masked too
- **WHEN** a mounted parent contains a nested repository, and a linked worktree whose common git directory lies under the same writable root
- **THEN** both the nested repository's hooks directory and the common directory's hooks directory are masked

#### Scenario: A mounted worktree common directory is masked
- **WHEN** a session launches from a linked worktree whose main repository lies outside the workspace and carries a `pre-commit` hook
- **THEN** the common directory's hooks directory is masked, lists empty in-cage, and the hook does not fire on an in-cage commit

#### Scenario: Opt-out restores host hooks
- **WHEN** `mask_git_hooks = false` is configured
- **THEN** no hooks directory is masked and the launch announces none

#### Scenario: A symlinked hooks directory refuses the launch
- **WHEN** a writable repository's `.git/hooks` (or its `.git` entry) is a symbolic link at launch
- **THEN** the launch is refused before any container starts, naming the link, its target and the fix

### Requirement: Operator can pin git config read-only

When `[landlock] protect_git_config = true` is configured (default `false`), the launcher SHALL pin each discovered git directory's `config` file (the common directory's for a linked worktree) read-only with a single-file bind of the real file over itself, for every git directory under a writable mount root, and SHALL announce each pin. Reads of the file SHALL work; every write, including git's own lock-and-rename, SHALL fail. The documentation SHALL list the in-cage operations this breaks (`git config`, `git remote add`, `push -u`, `branch --set-upstream-to`, `worktree add -b` with tracking, `gh pr checkout`) and those that keep working (`commit`, `push` without `-u`, `fetch`, `status`, `log`, `diff`), and SHALL state that this is the only preventive control here against `core.hooksPath`, `core.fsmonitor` and filter-driver redirection. These masks are mask-class mounts (read-only binds inside a writable tree), the same class as the dotenv masks, and are not subject to the mixed-writability mount rule.

#### Scenario: Config writes fail, commits work
- **WHEN** the pin is enabled and, inside the cage, the agent runs `git config x.y z`, `git remote add o https://example.invalid/r`, then `git commit`
- **THEN** the two config writes fail, the file is unchanged, and the commit succeeds

#### Scenario: Config stays readable
- **WHEN** the pin is enabled
- **THEN** `git config --list` and `git remote -v` inside the cage succeed

#### Scenario: Default is off
- **WHEN** `protect_git_config` is not configured
- **THEN** no config file is pinned and `git config x.y z` inside the cage succeeds
