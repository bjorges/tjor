# harness-launch Specification

## Purpose
How tjor builds the harness command line when it owns it: the harness name, the operator's per-harness arguments, a task prompt rendered from two placeholders, resume decided from the launcher's own record, and delivery to each harness in a form it reads as data.

## Requirements

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

`[harness.<name>] args` (`opencode`, `claude`, `copilot`) SHALL be read from the defaults and the user config only; a trusted repository config's `[harness]` is dropped with a warning, an untrusted file is ignored whole as today (ADR 0014). Each entry SHALL be a non-empty string without NUL or newline, at most 65536 bytes, not `--`; the list becomes one argv element per entry, before anything the launcher adds, never through a shell, never interpreted. Any other list SHALL refuse.

#### Scenario: Arguments precede what the launcher adds
- **WHEN** `[harness.claude] args = ["--model", "opus"]` and a task prompt are configured, and `tjor run --task a` starts a fresh conversation
- **THEN** the container's command is `claude --model opus -- <prompt>`

#### Scenario: A repository cannot set them
- **WHEN** a trusted repository config holds `[harness.opencode] args = ["--auto"]`
- **THEN** the table is ignored with a warning naming the file and the table, the launch uses the user config's arguments or none, and the configuration check reports the same; an unapproved file holding the table is ignored whole with the untrusted warning, as any unapproved file is

#### Scenario: Entries that are not plain strings
- **WHEN** an entry is a number, is empty, holds a newline or NUL, exceeds the bound, or is `--`
- **THEN** the launch is refused naming the entry's position and the rule, and nothing is created

#### Scenario: A flag the launcher is about to add
- **WHEN** the launcher is adding `--continue` for this launch and `args` holds `--continue` or `-c`, or it is adding the prompt and `args` holds `--prompt`, `--prompt=…`, `-i`, `--interactive` or `--interactive=…` for that harness
- **THEN** the launch is refused naming the entry and the `[task]` key that owns the flag; no other entry is inspected

### Requirement: Arguments are the operator's and may change what the harness does

tjor SHALL NOT claim to know the harnesses' flag sets. Beyond the exact collision rule, an `args` entry that selects a conversation (`--continue`, `--resume`, `--session-id`), supplies a prompt, or names a subcommand changes the harness's mode without tjor noticing, as do short-option clusters and parser abbreviations; `resume = "never"` and `--no-resume` suppress only what tjor adds. The launch line SHALL report tjor's decision, never verified harness behaviour.

#### Scenario: An operator's own resume flag
- **WHEN** `[harness.claude] args = ["--resume", "abc"]` and `resume = "never"` are configured
- **THEN** the launch passes `--resume abc` as given, adds nothing, and the launch line says the conversation is fresh from tjor's point of view; what Claude Code does with `--resume` is Claude Code's

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
- **THEN** the launch is refused naming the key and the offending text, and nothing is created

#### Scenario: Notes placeholder without notes
- **WHEN** the template uses `{task_dir}` and `task.notes_dir` is not set
- **THEN** the launch is refused naming both keys

#### Scenario: One-word prompt refused
- **WHEN** the template is `{task}` and the id is `mcp`, or the template is `{task}\n` or ` {task} ` with the same id
- **THEN** the launch is refused: a bare word is not accepted as a prompt, and surrounding whitespace does not make it one (the rule is judged on the prompt with leading and trailing whitespace removed), because Claude Code reads a bare positional that names one of its subcommands as that subcommand, `--` notwithstanding, and the rule is the same for every harness; the README says so where the template is documented

#### Scenario: No task, no prompt
- **WHEN** `[task] prompt` is set and `tjor run` is launched without `--task`
- **THEN** no prompt is sent and the command is the harness with its configured arguments

#### Scenario: A label-only id in the prompt
- **WHEN** no notes directory and no per-task session are configured, so the id grammar is the label grammar, and `--task -x` is given with the template `Task {task} starts.`
- **THEN** `Task -x starts.` is delivered as data: every helper receives the id in the attached form (`--task=-x`), and the delivery forms make a leading dash inert

### Requirement: The prompt is delivered in a form each harness reads as data

Delivery SHALL be: opencode `--prompt=<prompt>` as one argv element (attached form: a value starting with `-` stays a value); Claude Code `--` then the prompt as the positional argument (`--` ends option parsing, so a variadic option in `args` cannot swallow it); Copilot CLI `--interactive=<prompt>` as one element. The prompt and the continue flag SHALL follow the configured arguments. The image build SHALL check each pinned CLI's `--help` still lists the flags used.

#### Scenario: Delivery per harness
- **WHEN** the rendered prompt is `Task a begins.` and the launcher owns the command
- **THEN** opencode is started as `opencode [args…] --prompt=Task a begins.` (the last element holding the spaces), Claude Code as `claude [args…] -- Task a begins.`, and Copilot CLI as `copilot [args…] --interactive=Task a begins.`

#### Scenario: Variadic option before the prompt
- **WHEN** `[harness.claude] args = ["--add-dir", "/data"]` and the prompt `Task a begins.` is delivered
- **THEN** the command is `claude --add-dir /data -- Task a begins.` and Claude Code reads the prompt as the prompt, not as a second directory

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
- **THEN** no continue flag is added, the prompt is sent if one is configured, and the record is written once the container exists

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
- **THEN** the launch is refused naming the key and the two values, and nothing is created

#### Scenario: Reset forgets the conversation
- **WHEN** `tjor reset sessions` runs for the session
- **THEN** the record is deleted with the sessions tier and the next launch is fresh

### Requirement: The record is read as a bounded regular file and is never agent-writable

The record SHALL be read without following links: a link, a FIFO, a directory, any non-regular file, a file over 4096 bytes or one not in the launcher's exact format SHALL refuse the launch naming the file; only an absent path means "no conversation". When any intended writable root (the workspace, a `--dir`, or the notes directory before it is created) is or contains the state directory and the launch relies on the record, the launch SHALL be refused naming the root and the record.

#### Scenario: A record that cannot be read
- **WHEN** the record path is a symbolic link, a FIFO, a directory, an oversize file, or a file that is not the launcher's format
- **THEN** the launch is refused naming the file, the existing state directory and record are left exactly as they were, no credential is minted and no container is created; an unreadable record is never read as "no conversation"

#### Scenario: A planted file cannot force a resume
- **WHEN** the agent writes any file under its home, including one in the record's format
- **THEN** the decision is unaffected: the record lives at the state directory's root, which no container mounts

#### Scenario: A writable root over the state directory
- **WHEN** `tjor run --unsafe-dir --task a` is launched from the home directory, or with `--dir` naming the session root, with `prompt` set or `resume = "auto"`
- **THEN** the launch is refused naming the root and the record, because the agent could rewrite the record through that mount; a read-only root (`--dir-ro`) covering it is allowed, and so is the same launch with an explicit command or with `[task]` at its defaults

#### Scenario: The notes directory over the session root
- **WHEN** `task.notes_dir = "/safe/notes/{task}"`, the session root is `/safe/notes/a/sessions`, and `tjor run --unsafe-dir --task a` is launched from an unrelated repository with `resume = "auto"`
- **THEN** the launch is refused before the notes directory is created or mounted, naming `/safe/notes/a` and the record: the notes directory is judged as an intended writable root, not only the roots already resolved

#### Scenario: Coverage is judged without creating anything
- **WHEN** the session has no state directory yet (a fresh launch) and the check runs
- **THEN** it compares the writable roots with the session root and the state directory's path by filesystem identity where the paths exist and by the missing final component where they do not, creates nothing, and refuses on any error instead of reading it as "not covered"; the missing-component comparison is conservative: a name that differs from the session id only in case or Unicode composition (its canonical caseless form is the same) is refused on every filesystem, including a case-sensitive one that would keep the two apart, because nothing exists yet to compare identities; the remedy is a notes template that does not spell the session root

#### Scenario: Worktree common directories
- **WHEN** a linked worktree's common git directory would be mounted alongside the workspace
- **THEN** it is not part of this check: such a directory is refused by a sensitive-path check that has no override when it is one of tjor's roots or contains or lies under one, and the plan relies on that check by name

### Requirement: Refusals create nothing

The launcher SHALL validate the configuration and build the whole command, prompt and resume decision included, after the explicit extra-dir and notes sensitive-path gates and before the notes directory is created, the profile is staged, the first write, any mint and any sidecar. A refusal by any rule here SHALL create nothing: no notes directory, no state-directory content, no credential, no container. The session root and the lock, set up by every launch first, are all that remains.

#### Scenario: Malformed arguments leave nothing behind
- **WHEN** `[harness.opencode] args` holds a newline and `tjor run --task a` is launched for a session that has no state directory and a task whose notes directory does not exist
- **THEN** afterwards there is no state directory for the session, no notes directory, no minted credential and no container

#### Scenario: The record is read under the lock
- **WHEN** the launch reads the record to decide resume
- **THEN** it holds the session lock, so a concurrent `prune` or `reset` of the session cannot change the record between the decision and the launch

### Requirement: The launcher says what it built

Before starting the container the launcher SHALL print the command it built on one line, the prompt shown by its byte length rather than its text, and SHALL say whether the conversation is fresh (prompt sent or not) or continued, naming the record's task and time.

#### Scenario: Launch line
- **WHEN** `tjor run --task a` builds `claude --model opus -- <prompt>` for a fresh conversation
- **THEN** it prints the command with the prompt replaced by `<prompt: N bytes>` and states that the prompt was sent; an explicit command is printed as given

### Requirement: Limits are stated

The README SHALL state the limits in the scenarios below plainly, and the slide SHALL carry both.

#### Scenario: Limits of the owned command line
- **WHEN** the README's harness-launch section is read
- **THEN** it states that `args` are passed uninspected, so a flag that relaxes the harness's own permissions is the operator's choice; that an entry selecting a conversation, supplying a prompt or naming a subcommand changes the harness's mode without tjor noticing, clusters and abbreviations included, so `resume = "never"` and `--no-resume` suppress only what tjor adds; that a one-word prompt is refused, surrounding whitespace notwithstanding; that a notes directory whose last component differs from the session id only in case or composition is refused on every filesystem; and that the prompt is visible in the container's command line (`docker inspect`, the process list inside the cage), which the launch line's redaction does not change

#### Scenario: Limits of the record
- **WHEN** the same section is read
- **THEN** it states that the record says tjor started a conversation, not that the harness still holds one (a crash before the first message, a store cleared by hand), so the harness may report nothing to continue and `--no-resume` or `tjor reset sessions` is the remedy; that the record can be absent or stale (a crash between container creation and the write, an explicit command, a conversation switched inside the harness); that the launch line reports tjor's decision, not verified harness behaviour; that without `task.session_per_task` only the most recent conversation in a shared home can be continued; and that `tjor reset sessions` leaves Claude Code's transcripts on disk because their directory also holds its per-project memory
