# Security policy

tjor is a security boundary for AI coding agents. A weakness in it is a weakness in every session
it cages, so reports are welcome and taken seriously.

## Reporting

Report privately through GitHub's private vulnerability reporting:
https://github.com/bjorges/tjor/security/advisories/new

Do not open a public issue for something exploitable. Include the tjor version (`tjor doctor`),
the runtime (`tjor conformance` prints it), and the shortest reproduction you have. A probe in the
style of `images/conformance/probes.py` is ideal but not required.

## What counts

Anything that lets a caged agent do what the README says it cannot: reach a host outside the
allow-list, obtain a brokered credential, read a masked file, run code in the host's git, mount a
sensitive path, or make a session claim another's identity. Also anything that makes a tier
degrade silently rather than loudly.

## What to expect

This is a personal project maintained in personal time (ADR 0001). You will get an
acknowledgement, a fix on a branch, and a release whose `CHANGELOG.md` section names the class of
problem. Reports are credited in the changelog unless you ask otherwise. Supported: the latest
release only.
