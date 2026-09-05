# Installing tjor

## Prerequisites

- **bash ≥ 4.4**, **python3 ≥ 3.11** (with `tomllib`), **git**, **openssl**
- A **Docker engine with compose v2**: [Colima](https://github.com/abiosoft/colima)
  (`colima start` + `docker` + `docker-compose`), Docker Desktop, or a native
  Linux engine.

`tjor doctor` checks all of these and names anything missing.

## Install

```console
$ brew install bjorges/tap/tjor
```

Or run from a checkout (always builds images locally from source):

```console
$ git clone https://github.com/bjorges/tjor && ./tjor/bin/tjor doctor
```

## First run

```console
$ tjor doctor          # host preflight + policy + guarantee tiers
$ tjor conformance     # adversarial suite — proves the boundary holds on YOUR runtime
$ cd ~/your/project
$ tjor run             # caged session in this repo
```

An **installed** copy pulls a prebuilt agent image for its version on first
run (fast); a **git checkout** always builds locally. Either way the first
run may take a minute.

## Prebuilt images and trust

Prebuilt images live at `ghcr.io/bjorges/tjor-agent-<harness>` (public,
multi-arch amd64+arm64). Pulling a tag trusts GHCR and the publish pipeline;
building locally trusts only the audited Dockerfile and its SHA256-checked
downloads. To choose:

- **Verified pull** — pin the image by digest in `~/.config/tjor/config.toml`:
  ```toml
  [images.digests]
  opencode = "sha256:<digest from the release notes>"
  ```
- **Always build from source** — `[images] publish = false`.

A tag pull (no digest) prints an integrity notice each run. See
[ADR 0008](docs/decisions/0008-prebuilt-image-trust.md).

## Configuration

- Egress policy: `~/.config/tjor/policy.toml` (falls back to the shipped
  default) — strict allow-list; a policy that fails to parse denies everything.
- Broker, images, limits, identity: `~/.config/tjor/config.toml` (merged over
  the built-in defaults in `config/tjor.toml`).

## Uninstall

`tjor down` per session, `tjor gc` to reap idle topologies, then
`brew uninstall tjor`. Session state lives under `~/.tjor/`.
