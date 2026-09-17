## MODIFIED Requirements

### Requirement: Mount roots of different writability classes never overlap

Every approved mount root — the workspace included, whether or not it is a
git repository — SHALL be canonicalized to its physical path (symlinks
resolved) before it is recorded, before the session identity is derived
from it, and before any overlap comparison. After canonicalization, the
launch SHALL abort with a clear error naming both roots whenever a
read-only root (`--dir-ro`) and a writable root (the workspace or a
`--dir` path) stand in an ancestor/descendant relationship — in either
direction. Containment SHALL be judged on path-component boundaries:
`/a/b` overlaps `/a/b/c` but never `/a/b-other`. Rationale (normative): a
writable child bind under a read-only parent stays writable inside the
container; a writable parent's tree-wide git trust would cover
repositories inside a nested read-only child; and the kernel tier's
additive grants cannot subtract a read-only child from a writable-parent
grant — so a mixed-writability overlap falsifies the read-only guarantees
while the launch output still claims them; and two spellings of the same
physical tree must never evade that comparison.

For starts that bypass the launcher, the cage SHALL parse, normalize, and
validate both root lists into one shared representation **before**
read-only classification, overlap checking, git-trust registration, and
kernel-grant construction. It SHALL refuse (before the harness starts,
with the boundary exit code): malformed root spellings — relative paths,
empty values, repeated separators, `.` or `..` segments, carriage
returns, and wildcard-interpretable forms — in **either** list; any
read-only root that is not one of the approved roots; and any
cross-class overlap among the normalized roots. Same-class nesting
(writable under writable, read-only under read-only) is not a conflict
and SHALL launch normally.

#### Scenario: Read-only child under a writable parent aborts

- **WHEN** one invocation passes `--dir /p` and `--dir-ro /p/child` (in
  either flag order)
- **THEN** the launch aborts with an error naming both roots and the
  writability conflict

#### Scenario: Writable child under a read-only parent aborts

- **WHEN** one invocation passes `--dir-ro /p` and `--dir /p/child` (in
  either flag order)
- **THEN** the launch aborts with an error naming both roots and the
  writability conflict

#### Scenario: The workspace is a writable root for overlap purposes

- **WHEN** `tjor run --dir-ro <subdirectory of the workspace>` is invoked
- **THEN** the launch aborts with the writability-conflict error

#### Scenario: A symlinked workspace cannot evade the comparison

- **WHEN** tjor is launched from a non-git working directory reached
  through a symlink, with `--dir-ro` naming a physical-path descendant of
  that same directory
- **THEN** the launch aborts with the writability-conflict error before
  any container starts — the workspace is canonicalized physically, so
  alias and target compare in the same namespace

#### Scenario: Sibling name extension is not an overlap

- **WHEN** one invocation passes `--dir /p/b` and `--dir-ro /p/b-other`
- **THEN** the launch proceeds — containment is judged on component
  boundaries, not string prefixes

#### Scenario: Non-launcher starts are refused too

- **WHEN** the agent container is started directly with a root list in
  which a read-only root and a writable root overlap
- **THEN** the container refuses to start before the harness runs, with
  the boundary exit code

#### Scenario: A non-canonical read-only spelling cannot evade classification

- **WHEN** the agent container is started directly with a writable parent
  in the approved list and its read-only child spelled with a trailing
  slash in the read-only list
- **THEN** the container refuses to start with the boundary exit code —
  it neither treats the child as writable nor registers tree trust for it

#### Scenario: Malformed root spellings are refused at direct invocation

- **WHEN** the agent container is started directly with a root list entry
  that is relative, contains repeated separators or `.`/`..` segments, or
  carries a carriage return — or with a read-only root that is not among
  the approved roots
- **THEN** the container refuses to start with the boundary exit code
  before registering any trust
