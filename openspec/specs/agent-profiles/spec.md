# agent-profiles Specification

## Purpose
TBD - created by archiving change add-agent-profiles. Update Purpose after archive.

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
