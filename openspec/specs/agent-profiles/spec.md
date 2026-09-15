# agent-profiles Specification

## Purpose
Lets an operator opt a session into host-defined harness definitions (agents, commands, skills) from a named profile directory, staged credential-safely and overlaid on the image's instruction cargo — so personal tooling reaches the cage without importing any auth material.

## Requirements

### Requirement: Opt-in agent profile population

The launcher SHALL populate a session's active-harness config directory with
agent/command/skill definitions from a host **profile** the operator selects
explicitly — via `--profile <name>` (resolved from a `[profiles]` config map of
name → host dir) or `--profile-dir <path>`. With no profile selected, a session
SHALL behave exactly as if the feature did not exist.

#### Scenario: Profile agents reach the session
- **WHEN** a session is launched with `--profile-dir ~/.opencode` and that dir contains `agent/reviewer.md`
- **THEN** the definition is present in the harness config dir inside the cage (e.g. `~/.config/opencode/agent/reviewer.md`)

#### Scenario: No profile selected
- **WHEN** a session is launched without `--profile`/`--profile-dir` and no default profile is configured
- **THEN** no host definitions are deployed and the session is identical to one launched before this feature

### Requirement: Profiles never import host credentials

Profile population SHALL copy only an allow-list of definition subdirectories,
host-side, into a per-session staging area, and SHALL expose only that staging
area to the container. Credential and auth material in or beside the profile
source (e.g. `auth.json`, `*.credentials*`, API-key files, unknown top-level
files, symlinks resolving outside the source) SHALL NOT be copied, mounted, or
readable from inside the cage.

#### Scenario: Credential file beside definitions is not imported
- **WHEN** the profile source contains both `agent/reviewer.md` and `auth.json` (an API key)
- **THEN** `agent/reviewer.md` is deployed into the harness config, and `auth.json` is present nowhere in the container — not in the config dir and not at any mounted path

#### Scenario: Symlink escaping the source is not followed
- **WHEN** an allow-listed subdir contains a symlink pointing outside the profile source (e.g. to `~/.ssh/id_rsa`)
- **THEN** the symlink target is not staged and not exposed in the cage

### Requirement: Profile overlays instruction cargo

A deployed profile SHALL overlay the image's instruction cargo in the active
harness config directory — the versioned baseline is deployed first, then the
profile on top — so an operator definition wins on conflict, and the deploy
SHALL be symlink-safe against a persistent home.

#### Scenario: Profile definition overrides a baseline file
- **WHEN** the image cargo and the profile both provide a file at the same config path
- **THEN** the profile's version is what the harness reads in the session

### Requirement: Managed opencode configuration tier

A profile MAY provide `managed/opencode.json`. When staged, the cage SHALL
deploy it to opencode's managed-settings path (`/etc/opencode/opencode.json`)
owned by root and not writable, replaceable, or removable by the agent user —
so its settings load after, and cannot be overridden by, any user- or
project-level opencode configuration inside the cage. The deployment SHALL
happen before the harness starts. A staged `managed/opencode.json` that is
not valid JSON SHALL abort the launch before the harness starts (a session
must never look hardened without being it). When no profile stages a managed
file, any managed file left at that path from earlier activity SHALL be
removed, and behavior SHALL be identical to a session launched before this
capability existed. The `managed/` subdirectory SHALL NOT be copied into the
per-harness config overlay (it is not a harness definition directory), and
its staging SHALL pass through the same credential-filtering allow-list
pipeline as every other profile subdirectory.

#### Scenario: Managed settings are deployed agent-immutable

- **WHEN** a session is launched with a profile staging `managed/opencode.json`
- **THEN** `/etc/opencode/opencode.json` exists in the cage with that content,
  owned by root, and the agent user cannot write, replace, or remove it

#### Scenario: Invalid managed JSON refuses the launch

- **WHEN** the selected profile's `managed/opencode.json` is not valid JSON
- **THEN** the launch aborts with a clear error before the harness starts

#### Scenario: No managed file means no managed tier

- **WHEN** a session is launched with a profile that stages no
  `managed/opencode.json` (or with no profile at all)
- **THEN** `/etc/opencode/opencode.json` is absent in the cage, even if a
  previous launch had deployed one

#### Scenario: Managed file stays out of the harness config overlay

- **WHEN** a profile stages both `managed/opencode.json` and `agent/x.md`
- **THEN** the harness config dir receives `agent/x.md` but no `managed/`
  entry
