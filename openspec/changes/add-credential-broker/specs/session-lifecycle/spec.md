## MODIFIED Requirements

### Requirement: Garbage collection is safe by construction

`tjor gc` SHALL remove exited tjor agent containers, tear down topologies (sidecars, networks, volumes) that have had no running agent for longer than the age threshold (default 24h, `--age` to override), and support `--dry-run` listing exactly what would be removed. `gc` SHALL NEVER delete session state directories, and SHALL only ever delete docker resources carrying tjor session labels. When a broker credential exists for a session being torn down, `gc` SHALL revoke it (the D2 credential-broker hook) before removing the session's resources.

#### Scenario: Dry run first
- **WHEN** `tjor gc --dry-run` runs on a machine with reapable sessions
- **THEN** every candidate is listed and nothing is removed

#### Scenario: State survives collection
- **WHEN** `tjor gc` tears down an idle session's topology
- **THEN** the session's state directory (auth, history) is intact and a later `tjor run` in that repo resumes from it

#### Scenario: Brokered credential revoked on teardown
- **WHEN** `tjor gc` (or `tjor down`) tears down a session that holds a brokered credential
- **THEN** that credential is revoked before the session's resources are removed
