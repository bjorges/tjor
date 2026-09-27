# Spec Delta

## ADDED Requirements

### Requirement: Sensitive host paths are refused as the primary workspace

The sensitive-host-path refusal that governs `--dir` and `--dir-ro` SHALL
apply to the **primary workspace** as well. At launch, after the workspace is
resolved and canonicalized (version-control toplevel, else the physical
working directory) and **before** any per-session state directory is created
or any credential is minted, the launcher SHALL evaluate the workspace against
the sensitive set and SHALL abort the launch with a clear error when it
matches. `--unsafe-dir` is the single explicit override for the workspace,
exactly as for the extra-dir gates; when it actually overrides a refusal the
launcher SHALL print a loud warning naming the exposed path.

The **sensitive set** SHALL comprise: the filesystem root and system
directories; the user's home directory and every ancestor of it; the known
credential directories under the home directory; and — new with this
requirement — the effective session state root (`session.root`) and the
effective tjor user-config directory. For the two new roots, a candidate path
SHALL be refused when it **equals** the root, **contains** it (is an ancestor
of it), or **lies under** it, judged on path-component boundaries. Because the
same rule serves every gate, the two new roots are refused for `--dir` and
`--dir-ro` too. Custom locations (a non-default `session.root`, a non-default
config home) SHALL be honored — the check uses the effective values, not the
defaults.

When the workspace was reached by version-control discovery climbing **above**
the launch directory — the launch directory is not itself a repository root
and git resolved a sensitive toplevel — the error SHALL say so, naming the
launch directory, the resolved toplevel, and the discovery path (e.g.
`<cwd> is not a repository; git resolved the workspace to <toplevel> via
<toplevel>/.git — launch from a repository (or pass --unsafe-dir)`). A
sensitive workspace reached by the no-repository fallback gets the plain
refusal.

Read-only and teardown commands (`status`, `down`, `reset`, `denials`) resolve
the same workspace and SHALL NOT apply the gate: a session that was launched
under `--unsafe-dir` remains inspectable and removable from its workspace.

For starts that bypass the launcher, the cage SHALL refuse an approved mount
root that is the filesystem root or a system directory before the harness
starts, with the boundary exit code. The launcher's `--unsafe-dir` override
SHALL reach the cage and downgrade that refusal to a loud warning, so the
single override holds end to end. The home-directory, credential-directory,
session-root, and config-directory halves of the sensitive set depend on host
context the cage does not have and are a **launcher** guarantee; the cage
makes no claim to re-check them, and documentation SHALL NOT claim otherwise.

#### Scenario: Home-rooted dotfiles repository refused from the home directory

- **WHEN** the user's home directory is the work tree of a git repository and
  `tjor run` is invoked from the home directory without `--unsafe-dir`
- **THEN** the launch aborts, naming the home directory as a refused sensitive
  workspace, before any session state directory exists

#### Scenario: Discovery climbing to a sensitive toplevel is explained

- **WHEN** the user's home directory is the work tree of a git repository and
  `tjor run` is invoked from a subdirectory of it that is not itself a
  repository, without `--unsafe-dir`
- **THEN** the launch aborts with an error stating that the launch directory
  is not a repository, that git resolved the workspace to the home directory
  via its `.git`, and that the remedy is to launch from a repository or pass
  `--unsafe-dir`

#### Scenario: Override launches loudly

- **WHEN** `tjor run --unsafe-dir` is invoked with a workspace the gate would
  otherwise refuse
- **THEN** the launch proceeds and the launcher prints a warning naming the
  path that is now exposed to the agent

#### Scenario: Workspace equal to or containing the session root refused

- **WHEN** the resolved workspace equals the effective session state root, or
  is an ancestor of it, and `--unsafe-dir` is absent
- **THEN** the launch aborts with the sensitive-workspace error — including
  when `session.root` is configured outside the home directory

#### Scenario: Workspace under the session root refused

- **WHEN** `tjor run` is invoked from a directory inside a session's state
  directory (under the effective session root)
- **THEN** the launch aborts with the sensitive-workspace error

#### Scenario: Workspace equal to or under the config directory refused

- **WHEN** the resolved workspace is the effective tjor user-config directory
  or a directory under it — including a non-default config home
- **THEN** the launch aborts with the sensitive-workspace error

#### Scenario: Session root refused as an extra dir too

- **WHEN** `tjor run --dir <effective session root>` (or `--dir-ro`) is
  invoked without `--unsafe-dir`
- **THEN** the launch aborts with the sensitive-path error for that mount

#### Scenario: Ordinary repository workspace unchanged

- **WHEN** `tjor run` is invoked from an ordinary git repository (or a
  subdirectory of one) that is not in the sensitive set
- **THEN** the launch proceeds exactly as before, with no new warning

#### Scenario: Lifecycle commands ignore the gate

- **WHEN** `tjor down` (or `status`, `reset`, `denials`) is invoked from a
  workspace the launch gate would refuse
- **THEN** the command resolves the session and runs; the gate is not applied

#### Scenario: Non-launcher start with a system-directory root refused

- **WHEN** the agent container is started directly with an approved mount
  root that is the filesystem root or a system directory
- **THEN** the container refuses to start before the harness runs, with the
  boundary exit code

#### Scenario: The override reaches the cage

- **WHEN** the agent container is started with a system-directory mount root
  and the launcher's `--unsafe-dir` override set in its environment
- **THEN** the container prints a warning naming the root and starts
