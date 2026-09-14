## ADDED Requirements

### Requirement: Interactive sessions receive a PTY at container creation

When the launcher's stdin is a terminal, the agent container SHALL be created with a pseudo-TTY allocated, so the harness process observes an interactive stdin/stdout from its first instruction — independent of when (or whether) an attach client connects, and independent of any redirection or capture of the launcher's own stdout. After starting the agent container the launcher SHALL verify that a PTY was actually allocated when one was intended, and SHALL abort with a clear error if not — a session must never proceed into a state where the harness silently hangs or degrades because its stdin is a pipe.

When the launcher's stdin is not a terminal, the launch SHALL proceed without a PTY (one-shot commands still run to completion and propagate exit codes), and the launcher SHALL warn loudly that interactive harnesses will not work in that session.

#### Scenario: Interactive launch from a terminal
- **WHEN** `tjor run` is invoked from a terminal (even with the launcher's stdout captured or redirected)
- **THEN** the harness process sees a TTY on stdin and stdout at its own startup, before any attach client connects

#### Scenario: Typed input reaches the harness through attach
- **WHEN** a terminal client attaches to a running interactive session and sends input
- **THEN** the harness receives that input on its interactive stdin

#### Scenario: Non-terminal launch degrades loudly
- **WHEN** `tjor run` is invoked without a terminal on stdin
- **THEN** the session starts without a PTY, the launcher warns loudly that interactive harnesses will not work in this session, and a one-shot command still runs to completion and propagates its exit code

#### Scenario: Intended PTY missing aborts
- **WHEN** the launcher intended a PTY but the created agent container reports none allocated
- **THEN** the launch aborts with a clear error naming the problem instead of leaving a silently broken session running
