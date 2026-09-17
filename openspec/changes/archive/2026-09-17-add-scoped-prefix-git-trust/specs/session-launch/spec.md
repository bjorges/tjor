## ADDED Requirements

### Requirement: Git trust covers each writable approved mount root as a tree

The cage SHALL register git trust (`safe.directory`) for every **writable**
operator-approved mount root — the workspace and each `--dir` path — as a
**tree**: the root itself and every repository under it, at any depth,
including repositories and worktrees that come into existence during the
session. A git repository or worktree created inside the cage under a
writable approved root SHALL be immediately usable with git (no
dubious-ownership refusal, no re-launch, no manual registration step).

A **read-only** root (`--dir-ro`) SHALL keep exact-match registration only:
nested repositories under it are NOT automatically trusted. Rationale
(normative): git's ownership refusal is what prevents a hostile
pre-existing nested `.git/config` (fsmonitor, pager, filters, hooks,
repo-local credential helpers) from executing during read operations in
unvetted content, and a read-only mount blocks writes, not config
execution — while nothing new can be created under a read-only mount, so
tree trust is never needed there for the mid-session-creation case.

Trust SHALL remain scoped: a path outside every approved root stays
untrusted (git operations in a repository created outside the approved
roots still fail the ownership check), a sibling whose name merely extends
a root's name (e.g. `<root>-evil`) is not covered by `<root>/*`, and trust
SHALL never be registered as a bare wildcard covering arbitrary paths. Any
approved root whose registration would itself be wildcard-interpretable —
an empty value, the filesystem root `/`, a value that is literally `*`, or
a value ending in `/*` — SHALL abort the launch; trailing slashes SHALL be
normalized before registration.

The tree-wide grant is a documented, deliberate widening relative to
exact-path registration, and the widening is larger in kind, not only in
degree: it trusts every repository that exists or will ever exist under the
root — including nested or vendored repositories the operator never
individually reviewed. Restricting it to writable roots is the design's
answer: under a writable root the operator has already accepted
agent-driven mutation of the whole tree. The documentation SHALL state this
honestly.

#### Scenario: Worktree created mid-session is trusted

- **WHEN** the agent runs `git worktree add <writable-root>/.worktrees/wt1`
  inside the cage and then runs `git status` (or `log`, `diff`) in the new
  worktree
- **THEN** the operations succeed with no dubious-ownership refusal

#### Scenario: Repo cloned mid-session under a writable root is trusted

- **WHEN** the agent creates or clones a new repository under a writable
  approved mount root during the session
- **THEN** git operations in it succeed immediately

#### Scenario: Nested pre-existing repos under a writable mounted parent work

- **WHEN** a session mounts a parent directory via `--dir` that contains
  multiple git repositories at launch
- **THEN** git operations work in each nested repository without
  per-repository registration

#### Scenario: Nested repos under a read-only parent stay untrusted

- **WHEN** a session mounts a parent directory via `--dir-ro` that contains
  a nested git repository owned by another uid
- **THEN** git refuses the nested repository with the ownership check — the
  read-only mount's protection against pre-existing hostile git config is
  preserved, and the documented alternatives are mounting the individual
  repos `--dir-ro` or mounting the parent writable

#### Scenario: Outside the approved roots stays untrusted

- **WHEN** a repository exists at a container path outside every approved
  mount root (e.g. created under `/tmp` in-cage) and its owner differs from
  the agent user
- **THEN** git refuses it with the ownership check

#### Scenario: A sibling name extension is not covered

- **WHEN** `<root>` is a writable approved root and a repository exists at
  `<root>-evil/repo` (a sibling whose name extends the root's), owned by
  another uid
- **THEN** git refuses it — `<root>/*` matches only paths under `<root>`

#### Scenario: Symlink escape does not extend trust

- **WHEN** a symlink under a writable approved root points at a repository
  outside every approved root, and git is run against the resolved target
- **THEN** the out-of-root repository is still refused by the ownership
  check

#### Scenario: Degenerate root aborts the launch

- **WHEN** an approved mount root resolves to a value whose registration
  would itself be wildcard-interpretable (empty, `/`, literally `*`, or
  ending in `/*`)
- **THEN** the launch aborts with a clear error before the agent starts —
  such an entry would be blanket trust of arbitrary paths, which is never
  registered
