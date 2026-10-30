## Purpose

How tjor builds the harness command line when it owns it: the harness name, the operator's per-harness arguments, a task prompt rendered from two placeholders, resume decided from the launcher's own record, and delivery to each harness in a form it reads as data.

## ADDED Requirements

### Requirement: The harness name is one of three

`--harness` SHALL accept exactly `opencode`, `claude` and `copilot`. Any other value SHALL refuse the launch naming the value and the three names, before any session state exists.

#### Scenario: Unknown harness refused
- **WHEN** `tjor run --harness foo` is given
- **THEN** the launch is refused naming `foo` and the three accepted names, and no state directory, credential or container is created

### Requirement: An explicit command replaces everything

When the command line carries a command after the options, with or without `--`, the launcher SHALL pass it to the container unchanged, as today: no configured arguments, no prompt and no continue flag are added, and the launch record is neither read nor written.

#### Scenario: Explicit command with `--`
- **WHEN** `[harness.opencode] args` and `[task] prompt` are configured and `tjor run --task a -- opencode --help` is launched
- **THEN** the container's command is exactly `opencode --help`

#### Scenario: Explicit command without `--`
- **WHEN** the same configuration is in place and `tjor run --task a opencode --help` is launched
- **THEN** the container's command is exactly `opencode --help`, as before this change

#### Scenario: The record is left alone
- **WHEN** a session's launch record names a conversation for task `a` and `tjor run --task a -- claude` is launched
- **THEN** the record is unchanged afterwards

### Requirement: Configured harness arguments come from the user configuration and pass verbatim

`[harness.<name>] args` (`opencode`, `claude`, `copilot`) SHALL be read from the defaults and the user config only; a repository config's `[harness]` table is dropped with a warning, trusted or not (ADR 0014). Each entry SHALL be a string without NUL or newline, at most 65536 bytes, not `--`; the list becomes one argv element per entry, before anything the launcher adds, never through a shell, never interpreted. Any other list SHALL refuse the launch.

#### Scenario: Arguments precede what the launcher adds
- **WHEN** `[harness.claude] args = ["--model", "opus"]` and a task prompt are configured, and `tjor run --task a` starts a fresh conversation
- **THEN** the container's command is `claude --model opus -- <prompt>`

#### Scenario: A repository cannot set them
- **WHEN** a trusted repository config holds `[harness.opencode] args = ["--auto"]`
- **THEN** the table is ignored with a warning naming the file and the table, the launch uses the user config's arguments or none, and the configuration check reports the same

#### Scenario: Entries that are not plain strings
- **WHEN** an entry is a number, holds a newline or NUL, exceeds the bound, or is `--`
- **THEN** the launch is refused naming the entry's position and the rule, before any session state exists

#### Scenario: A flag the launcher is about to add
- **WHEN** the launcher is adding `--continue` for this launch and `args` holds `--continue` or `-c`, or it is adding the prompt and `args` holds `--prompt`, `--prompt=…`, `-i`, `--interactive` or `--interactive=…` for that harness
- **THEN** the launch is refused naming the entry and the `[task]` key that owns the flag; no other entry is inspected

### Requirement: The task prompt is rendered from two placeholders

`[task] prompt` SHALL be rendered by literal substitution of `{task}` (the id) and `{task_dir}` (the notes directory's path), with `{{` and `}}` standing for literal braces; any other brace SHALL refuse. `{task_dir}` with no notes directory configured SHALL refuse. The rendered prompt SHALL hold no NUL, at most 65536 bytes, and at least one whitespace and one other character. It SHALL be sent only with `--task`, only on a fresh conversation, and only when the launcher owns the command.

#### Scenario: Fresh launch with a prompt
- **WHEN** `[task] prompt = "Task {task}. Notes: {task_dir}."`, a notes directory is configured, and `tjor run --task a` starts a fresh conversation
- **THEN** the harness receives `Task a. Notes: /home/me/scratch/tasks/a.` as its first message

#### Scenario: Literal braces
- **WHEN** the template is `Reply as {{"task": "{task}"}}` for task `a`
- **THEN** the rendered prompt is `Reply as {"task": "a"}`

#### Scenario: Unknown placeholder or stray brace
- **WHEN** the template holds `{taks}`, a lone `{` or a lone `}`
- **THEN** the launch is refused naming the key and the offending text, before any session state exists

#### Scenario: Notes placeholder without notes
- **WHEN** the template uses `{task_dir}` and `task.notes_dir` is not set
- **THEN** the launch is refused naming both keys

#### Scenario: One-word prompt refused
- **WHEN** the template is `{task}` and the id is `mcp`
- **THEN** the launch is refused: a bare word is not accepted as a prompt, because Claude Code reads a bare positional that names one of its subcommands as that subcommand, `--` notwithstanding, and the rule is the same for every harness

#### Scenario: No task, no prompt
- **WHEN** `[task] prompt` is set and `tjor run` is launched without `--task`
- **THEN** no prompt is sent and the command is the harness with its configured arguments

#### Scenario: A label-only id in the prompt
- **WHEN** no notes directory and no per-task session are configured, so the id grammar is the label grammar, and `--task -x` is given with the template `Task {task} starts.`
- **THEN** `Task -x starts.` is delivered as data; the delivery forms make a leading dash inert

### Requirement: The prompt is delivered in a form each harness reads as data

Delivery SHALL be: opencode `--prompt=<prompt>` as one argv element (attached form: a value starting with `-` stays a value); Claude Code `--` then the prompt as the positional argument (`--` ends option parsing, so a variadic option in `args` cannot swallow it); Copilot CLI `--interactive=<prompt>` as one element. The prompt and the continue flag SHALL follow the configured arguments. The image build SHALL check each pinned CLI's `--help` still lists the flags used.

#### Scenario: Delivery per harness
- **WHEN** the rendered prompt is `P` and the launcher owns the command
- **THEN** opencode is started as `opencode [args…] --prompt=P`, Claude Code as `claude [args…] -- P`, and Copilot CLI as `copilot [args…] --interactive=P`

#### Scenario: Variadic option before the prompt
- **WHEN** `[harness.claude] args = ["--add-dir", "/data"]` and a prompt is delivered
- **THEN** the command is `claude --add-dir /data -- P` and Claude Code reads `P` as the prompt, not as a second directory

#### Scenario: Flag drift at the pin
- **WHEN** a harness version is bumped and its `--help` no longer lists the flag tjor uses for the prompt or for resume
- **THEN** the image build fails naming the harness and the flag

### Requirement: Resume is decided from the launcher's own record

`[task] resume` SHALL be `"never"` (default) or `"auto"`; any other value SHALL refuse. On a launch it owns with `--task` and `prompt` set or `resume = "auto"`, the launcher SHALL write a record (harness, task, time) at the state directory's root, which no container mounts, once the agent container exists. With `auto`, a record naming this harness and task SHALL add the continue flag and send no prompt; otherwise the conversation is fresh. The harness's store is never inspected.

#### Scenario: Relaunch continues
- **WHEN** `resume = "auto"`, `tjor run --task a` ran before with the same harness, and the session is launched again
- **THEN** the command carries `--continue`, no prompt is sent, and the launcher says which recorded conversation it continues

#### Scenario: First launch under auto
- **WHEN** `resume = "auto"` and the session has no record
- **THEN** no continue flag is added, the prompt is sent, and the record is written once the container exists

#### Scenario: Another task or harness in the same session
- **WHEN** the record names task `a` under `claude` and the launch is `--task b`, or `--task a` under `opencode`
- **THEN** the conversation is fresh, the prompt is sent, and the record is replaced once the container exists

#### Scenario: Forced fresh
- **WHEN** `tjor run --task a --no-resume` is launched with a record that would otherwise continue
- **THEN** `--no-resume` forces a fresh conversation for this launch: the prompt is sent and the record is rewritten

#### Scenario: Never
- **WHEN** `resume = "never"` or the key is absent, and a prompt is configured
- **THEN** no continue flag is ever added, every launch sends the prompt, and the record is still written, so a later switch to `auto` continues from the next launch on

#### Scenario: Invalid value
- **WHEN** `resume = "always"` is configured
- **THEN** the launch is refused naming the key and the two values, before any session state exists

#### Scenario: A record that cannot be read
- **WHEN** the record exists but is not the launcher's format, or cannot be read
- **THEN** the launch is refused naming the file; an unreadable record is never read as "no conversation"

#### Scenario: Reset forgets the conversation
- **WHEN** `tjor reset sessions` runs for the session
- **THEN** the record is deleted with the sessions tier and the next launch is fresh

#### Scenario: A planted file cannot force a resume
- **WHEN** the agent writes any file under its home, including one in the record's format
- **THEN** the decision is unaffected: the record lives at the state directory's root, which no container mounts

### Requirement: Refusals precede any session state

The launcher SHALL validate the configuration and build the whole command, prompt and resume decision included, after the profile gate and before its first write into the state directory, before any credential is minted and before any sidecar exists. A refusal by any rule in this capability SHALL leave no state directory, no credential and no container behind.

#### Scenario: Malformed arguments leave nothing behind
- **WHEN** `[harness.opencode] args` holds a newline and `tjor run` is launched for a session that has no state directory
- **THEN** afterwards there is no state directory for the session, no minted credential and no container

#### Scenario: The record is read under the lock
- **WHEN** the launch reads the record to decide resume
- **THEN** it holds the session lock, so a concurrent `prune` or `reset` of the session cannot change the record between the decision and the launch

### Requirement: The launcher says what it built

Before starting the container the launcher SHALL print the command it built on one line, the prompt shown by its byte length rather than its text, and SHALL say whether the conversation is fresh (prompt sent or not) or continued, naming the record's task and time.

#### Scenario: Launch line
- **WHEN** `tjor run --task a` builds `claude --model opus -- <prompt>` for a fresh conversation
- **THEN** it prints the command with the prompt replaced by `<prompt: N bytes>` and states that the prompt was sent; an explicit command is printed as given

### Requirement: Limits are stated

The README SHALL state the limits in the scenario below plainly.

#### Scenario: Limits in the README
- **WHEN** the README's harness-launch section is read
- **THEN** it states that `args` are passed uninspected, so a flag that relaxes the harness's own permissions is the operator's choice; that the record says tjor started a conversation, not that the harness still holds one, so after a crash before the first message or a store cleared by hand the harness reports nothing to continue and `--no-resume` or `tjor reset sessions` is the remedy; that without `task.session_per_task` one session home serves every task, so only the most recent conversation can be continued; and that `tjor reset sessions` leaves Claude Code's transcripts on disk because their directory also holds its per-project memory
