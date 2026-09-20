# Spec Delta

## ADDED Requirements

### Requirement: Workload-log read volume is observable per session

As the observability half of the log-access trade-off (#50), tjor SHALL measure how much workload-log content a session reads and surface it at teardown, without altering, blocking, delaying, or rate-limiting the read. For responses to the Kubernetes log endpoint (request path matching `/api/v1/namespaces/<namespace>/pods/<pod>/log`) on a configured cluster API host, the proxy SHALL accumulate the response body size for the session, attributed per pod, including bodies read via streaming/`follow` reads. At session teardown, `tjor down` SHALL report the total bytes read and the number of distinct pods when any workload-log content was read, and SHALL stay silent when none was. The recap SHALL surface only these aggregate figures, not individual pod identifiers; any agent-influenced identifier that is ever rendered SHALL pass through the terminal-escape sanitizer used for the denial recap. Measurement SHALL be best-effort and fail-safe: a failure to record volume SHALL never break, alter, or fail-open a request. This requirement adds no enforcement — no threshold, deny, rate limit, or new configuration surface; enforcement, if ever, is specified separately once real volumes are known.

#### Scenario: A workload-log read is counted

- **WHEN** the agent reads a pod's logs through the proxy from a configured cluster API host (`GET /api/v1/namespaces/<ns>/pods/<pod>/log`)
- **THEN** the response is returned unchanged (not blocked, altered, or delayed)
- **AND** the session's workload-log byte total is increased by the response body size, attributed to that pod

#### Scenario: Streaming/follow reads are counted

- **WHEN** the agent reads logs with `follow=true` (a streamed, potentially large body)
- **THEN** the streamed bytes are still counted toward the session total without buffering the whole body to alter it

#### Scenario: Non-log traffic is not counted

- **WHEN** the agent makes any request that is not a `pods/log` read on a configured cluster API host (other API calls, ordinary egress)
- **THEN** nothing is added to the workload-log volume total

#### Scenario: Teardown surfaces the volume

- **WHEN** `tjor down` runs for a session that read workload-log content
- **THEN** it reports the total volume read and the number of distinct pods (aggregate figures only, no individual pod identifiers)
- **AND** it reports nothing about workload-log volume when the session read none

#### Scenario: Counting never breaks a request

- **WHEN** recording the read volume fails for any reason
- **THEN** the request/response still completes normally and the failure is swallowed (no fail-open, no altered response)
