## ADDED Requirements

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

### Requirement: Kernel grants for read-only mounts are read-only

When the kernel-sandbox tier is active, a repository mounted read-only
(`--dir-ro`) SHALL be granted read access but not write access in the kernel
ruleset — the kernel tier and the container-level read-only mount SHALL agree,
so no layer reports the tree as writable.

#### Scenario: Kernel denies writes into a read-only mount

- **WHEN** the tier is active and the harness attempts to write under a
  `--dir-ro` mounted tree
- **THEN** the write is denied, and reads of the same tree succeed
