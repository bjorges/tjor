## ADDED Requirements

### Requirement: The sessions tier names every conversation store and the launch record

The `sessions` tier SHALL include, besides the paths it holds today, opencode's database (`home/.local/share/opencode/opencode.db`, `-wal`, `-shm`), Copilot CLI's `home/.copilot/session-state`, and the launcher's `conversation.json` at the state directory's root, so `tjor reset sessions` ends the recorded conversation and removes those stores together. Claude Code's transcripts SHALL NOT be in the tier: their directory also holds its per-project memory; the README SHALL state it.

#### Scenario: Reset ends the recorded conversation
- **WHEN** `tjor reset sessions` runs for a session whose record names a conversation
- **THEN** the record, the opencode database files and the Copilot session state are deleted (a dry run lists them), and the next launch under `resume = "auto"` is fresh

#### Scenario: Claude transcripts stay
- **WHEN** `tjor reset sessions` runs for a Claude Code session
- **THEN** `home/.claude/projects` is left on disk, the record is gone, and the next launch does not continue the old conversation
