# Spec Delta

## ADDED Requirements

### Requirement: A profile may declare how its harness is launched

A profile directory MAY hold `profile.toml` with `[harness.<name>] args = [...]` per harness. The launcher SHALL read it host-side when the profile is selected and SHALL apply it as the `harness-launch` capability states (the profile's list wins over the config's for that harness). The file SHALL never be staged into the cage (it is not a definition directory), and an unknown key in it SHALL refuse the launch naming the file and the key.

#### Scenario: Profile args applied, file not staged
- **WHEN** a selected profile holds `profile.toml` with `[harness.opencode] args = ["--agent", "rev"]`
- **THEN** the opencode command line carries `--agent rev`, and `profile.toml` is present nowhere in the container

#### Scenario: Typo in the profile file
- **WHEN** `profile.toml` holds `[harness.opencode] arg = ["x"]`
- **THEN** the launch is refused naming the file and the key, before any container exists

#### Scenario: No file, no change
- **WHEN** a selected profile holds no `profile.toml`
- **THEN** the launch is as before this capability existed
