## ADDED Requirements

### Requirement: Mount roots of different writability classes never overlap

After resolving every approved mount root to its canonical absolute path,
the launch SHALL abort with a clear error naming both roots whenever a
read-only root (`--dir-ro`) and a writable root (the workspace or a
`--dir` path) stand in an ancestor/descendant relationship — in either
direction. Containment SHALL be judged on path-component boundaries:
`/a/b` overlaps `/a/b/c` but never `/a/b-other`. Rationale (normative): a
writable child bind under a read-only parent stays writable inside the
container; a writable parent's tree-wide git trust would cover
repositories inside a nested read-only child; and the kernel tier's
additive grants cannot subtract a read-only child from a writable-parent
grant — so a mixed-writability overlap falsifies the read-only guarantees
while the launch output still claims them. The cage SHALL independently
refuse such a root set at container start (for launches that bypass the
launcher). Same-class nesting (writable under writable, read-only under
read-only) is not a conflict and SHALL launch normally.

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

#### Scenario: Sibling name extension is not an overlap

- **WHEN** one invocation passes `--dir /p/b` and `--dir-ro /p/b-other`
- **THEN** the launch proceeds — containment is judged on component
  boundaries, not string prefixes

#### Scenario: Non-launcher starts are refused too

- **WHEN** the agent container is started directly with a root list in
  which a read-only root and a writable root overlap
- **THEN** the container refuses to start before the harness runs, with
  the boundary exit code
