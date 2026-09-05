## MODIFIED Requirements

### Requirement: Single config merge path

Every entry point SHALL obtain effective configuration through one shared merge implementation covering all config sections. When the current repo carries a `.tjor/config.toml` that the user has approved (`repo-config-trust`), it layers over the user config in that one merge path; an unapproved repo config is excluded from the merge.

#### Scenario: Override honored everywhere
- **WHEN** a user override is set for any config section
- **THEN** every entry point (launcher, debug CLI, topology setup) observes the same effective value

#### Scenario: Trusted repo layer applies through the same path
- **WHEN** an approved repo `.tjor/config.toml` sets a value
- **THEN** every entry point observes it via the same merge path, layered over the user config
