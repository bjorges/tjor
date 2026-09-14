## MODIFIED Requirements

### Requirement: Operator can extend the deny list

The `[landlock]` config SHALL accept additional deny paths (`deny_paths`) that are applied as launch-time masks. Configuration SHALL only extend the default deny set, never weaken it. `deny_paths` SHALL be applied independently of `mask_dotenv`: disabling the automatic dotenv discovery never disables, weakens, or silently drops an explicitly configured deny path.

#### Scenario: Extra deny path enforced
- **WHEN** the config adds a deny path naming a file present at launch
- **THEN** reads of that path from inside the cage return no secret content

#### Scenario: Deny paths survive disabling dotenv masking
- **WHEN** the config sets `mask_dotenv = false` and adds a deny path naming a file present at launch
- **THEN** the deny path is masked at launch (and announced), while automatic dotenv discovery is skipped
