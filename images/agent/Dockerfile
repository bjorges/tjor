# syntax=docker/dockerfile:1
# tjor agent image. All versions and digests arrive as build args from
# config/tjor.toml via the launcher — nothing version-shaped is hardcoded
# here (charter L8), and every binary download passes a checksum gate before
# unpacking (charter L23; threat model documented in config/tjor.toml).
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git gh openssh-client jq ripgrep less procps \
        gosu python3 unzip \
    && rm -rf /var/lib/apt/lists/*

# HARNESS is a comma list: any of opencode, claude, copilot.
ARG HARNESS=opencode
ARG TARGETARCH

# --- opencode: single binary from GitHub releases, sha256-gated -------------
ARG OPENCODE_VERSION
ARG OPENCODE_SHA256_ARM64
ARG OPENCODE_SHA256_X64
RUN set -eu; \
    case ",${HARNESS}," in *,opencode,*) \
        case "${TARGETARCH}" in \
            arm64) asset="opencode-linux-arm64.tar.gz"; sha="${OPENCODE_SHA256_ARM64}" ;; \
            amd64) asset="opencode-linux-x64.tar.gz"; sha="${OPENCODE_SHA256_X64}" ;; \
            *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
        esac; \
        [ -n "${OPENCODE_VERSION}" ] && [ -n "${sha}" ] || { echo "missing opencode version/sha build args" >&2; exit 1; }; \
        curl -fsSLo /tmp/opencode.tgz \
            "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/${asset}"; \
        echo "${sha}  /tmp/opencode.tgz" | sha256sum -c -; \
        mkdir -p /tmp/oc; tar -C /tmp/oc -xzf /tmp/opencode.tgz; \
        bin="$(find /tmp/oc -type f -name opencode | head -1)"; \
        [ -n "${bin}" ] || { echo "opencode binary not found in archive" >&2; exit 1; }; \
        install -m 0755 "${bin}" /usr/local/bin/opencode; \
        rm -rf /tmp/opencode.tgz /tmp/oc ;; \
    esac

# --- claude / copilot: npm, exact-version pinned ----------------------------
ARG CLAUDE_CODE_VERSION
ARG COPILOT_VERSION
RUN set -eu; \
    case ",${HARNESS}," in \
        *,claude,*|*,copilot,*) \
            apt-get update && apt-get install -y --no-install-recommends nodejs npm \
            && rm -rf /var/lib/apt/lists/* ;; \
    esac; \
    case ",${HARNESS}," in *,claude,*) \
        [ -n "${CLAUDE_CODE_VERSION}" ] || { echo "missing CLAUDE_CODE_VERSION" >&2; exit 1; }; \
        npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" ;; \
    esac; \
    case ",${HARNESS}," in *,copilot,*) \
        [ -n "${COPILOT_VERSION}" ] || { echo "missing COPILOT_VERSION" >&2; exit 1; }; \
        npm install -g "@github/copilot@${COPILOT_VERSION}" ;; \
    esac

# Match the host user's uid so bind-mounted session state stays writable.
ARG AGENT_UID=1000
RUN useradd -m -u ${AGENT_UID} -s /bin/bash agent

COPY images/agent/instructions/ /opt/tjor/instructions/
COPY images/agent/entrypoint.sh /usr/local/bin/tjor-entrypoint
RUN chmod 0755 /usr/local/bin/tjor-entrypoint

ENV TJOR_CAGE=1
ENTRYPOINT ["/usr/local/bin/tjor-entrypoint"]
CMD ["opencode"]
