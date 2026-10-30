# Spec Delta

## Purpose
How tjor builds the harness command line when configuration asks it to: configured arguments, a task-aware first prompt, and conversation resume, delivered in each harness's own way, with an explicit command on the command line always winning.

## ADDED Requirements

### Requirement: An explicit command on the command line replaces everything

When `tjor run` is given `-- <cmd...>`, the agent SHALL run exactly that command: no configured arguments, no prompt and no resume flag are added, as before this capability existed. Without `-- <cmd...>` and without any of the settings below, the command line SHALL be the bare harness, as before.

#### Scenario: Explicit command wins
- **WHEN** `[harness.opencode].args` and `[task].prompt` are configured and `tjor run --task a -- opencode --help` is launched
- **THEN** the container runs `opencode --help` and nothing else

#### Scenario: Nothing configured
- **WHEN** no `[harness.*].args`, no profile `profile.toml`, no `[task].prompt` and `[task].resume = "never"` are in effect
- **THEN** the command line is the bare harness, byte for byte as today

### Requirement: Configured harness arguments are passed verbatim

A list `[harness.<name>].args` (one table per harness: `opencode`, `claude`, `copilot`) SHALL be appended to that harness's command line, one argv element per entry, never through a shell. A selected profile's `profile.toml` MAY carry the same table and SHALL win over the config's list for that harness. An entry that is not a string, or holds a NUL or newline, SHALL refuse the launch naming it. The arguments SHALL come before the prompt and the resume flag.

#### Scenario: Args from config
- **WHEN** `[harness.opencode] args = ["--agent", "bob"]` is configured and `tjor run` is launched with the opencode harness
- **THEN** the container's command line is `opencode --agent bob`

#### Scenario: Args from a profile win
- **WHEN** the config sets `[harness.opencode] args = ["--agent", "bob"]` and the selected profile's `profile.toml` sets `[harness.opencode] args = ["--agent", "rev"]`
- **THEN** the command line carries `--agent rev` and not `bob`

#### Scenario: Another harness's args are not applied
- **WHEN** only `[harness.claude].args` is configured and the opencode harness is launched
- **THEN** nothing is added

#### Scenario: A malformed entry refuses
- **WHEN** an `args` entry is a number or holds a newline
- **THEN** the launch is refused naming the entry, before any container exists

### Requirement: The task prompt is rendered from two placeholders and delivered per harness

When `[task].prompt` is set and the launch carries `--task <id>`, the launcher SHALL render the template with `{task}` (the id) and `{task_dir}` (the notes directory) and deliver it as one argv element in the harness's own way. A template holding any other `{…}` SHALL refuse the launch; one using `{task_dir}` with no notes directory configured SHALL refuse too. Without `--task` no prompt is sent; it is sent only when a fresh conversation starts.

#### Scenario: Prompt delivered on a fresh launch
- **WHEN** `[task] prompt = "Task {task}; notes in {task_dir}."`, a notes directory is configured, and `tjor run --task a` is launched with the opencode harness for the first time
- **THEN** the command line ends in `--prompt "Task a; notes in /home/u/scratch/tasks/a."` (one argument, no shell)

#### Scenario: Delivery per harness
- **WHEN** the same launch uses the opencode, claude or copilot harness
- **THEN** the prompt follows `--prompt` for opencode, is the trailing positional argument for claude, and follows `-i` for copilot

#### Scenario: Missing notes directory for the placeholder
- **WHEN** the template holds `{task_dir}` and no `task.notes_dir` is configured
- **THEN** the launch is refused naming the placeholder

#### Scenario: Unknown placeholder refuses
- **WHEN** the template holds `{workspace}`
- **THEN** the launch is refused naming the placeholder, before any container exists

#### Scenario: No task, no prompt
- **WHEN** `[task].prompt` is set and `tjor run` is launched without `--task`
- **THEN** no prompt is added and the launch proceeds

### Requirement: Resume continues an existing conversation instead of starting one

With `[task] resume = "auto"` and `--task <id>`, when the session's home already holds a conversation for the launched harness, the launcher SHALL add that harness's continue flag (`--continue`) and send no prompt; otherwise it SHALL start fresh and send the prompt if configured. Detection SHALL be host-side on the session state directory, never through a link, before the container is created. `resume = "never"` (the default) SHALL never add the flag; any other value SHALL refuse the launch.

#### Scenario: Relaunch continues
- **WHEN** `resume = "auto"`, a prompt is configured, and the session for task `a` is relaunched after its opencode home gained a session in its storage
- **THEN** the command line carries `--continue` and no `--prompt`

#### Scenario: Fresh launch under auto
- **WHEN** `resume = "auto"` and the session home holds no conversation for the harness
- **THEN** no `--continue` is added and the prompt is sent

#### Scenario: Never
- **WHEN** `resume = "never"` and the home holds a conversation
- **THEN** no `--continue` is added; the prompt is sent on every launch with `--task`

#### Scenario: Where a conversation is looked for
- **WHEN** the launcher decides whether a conversation exists
- **THEN** it looks at the harness's own store under the session home: opencode `.local/share/opencode/storage` holding a session, Claude Code `.claude/projects` holding a transcript, Copilot CLI its session store under `.copilot`, each path confirmed against a real session home and recorded here

#### Scenario: An invalid value refuses
- **WHEN** `[task] resume = "sometimes"`
- **THEN** the launch is refused naming the value

#### Scenario: Another harness's conversation does not count
- **WHEN** `resume = "auto"`, the home holds a claude transcript and the opencode harness is launched
- **THEN** opencode starts fresh

### Requirement: The launcher says what it built

A launch whose command line tjor built SHALL print it: the harness and every argument verbatim through the terminal-escape sanitizer, the prompt by its length (`+ prompt (N characters)`), and `--continue` when added. An explicit `-- cmd` launch SHALL print nothing new.

#### Scenario: The launch line
- **WHEN** args, a prompt and resume apply
- **THEN** the launch output holds one line naming the harness, the args, `--continue` or `+ prompt (N characters)`, in that order

### Requirement: Limits are stated

The README SHALL state: the rendered prompt is a process argument, visible to anyone who can inspect the container, and nothing in it should be secret; `--continue` continues the harness's most recent conversation within that session home, which is the task's conversation only under per-task sessions; the `[task]` table, prompt included, is user-config only (ADR 0013); a repository steers the agent through its instruction files, not a launch prompt.

#### Scenario: Limits in the README
- **WHEN** the README's harness-launch section is read
- **THEN** each limit above is stated plainly
