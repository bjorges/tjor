#!/bin/sh
# tjor proxy entrypoint. Replaces the base image's, whose group alignment
# (usermod -g <confdir gid>) crash-loops when the bind-mounted confdir's gid
# has no matching group inside the container (native Linux CI runners).
# Only the UID needs aligning: that is what grants the mitmproxy user read
# access to the launcher-generated CA key in the confdir.
set -eu

DIR=/home/mitmproxy/.mitmproxy
mkdir -p "$DIR"

if [ "$(id -u)" = "0" ]; then
    owner_uid="$(stat -c %u "$DIR")"
    if [ "$owner_uid" != "0" ] && [ "$owner_uid" != "$(id -u mitmproxy)" ]; then
        usermod -o -u "$owner_uid" mitmproxy
    fi
    if command -v gosu >/dev/null 2>&1; then
        exec gosu mitmproxy "$@"
    fi
    if command -v su-exec >/dev/null 2>&1; then
        exec su-exec mitmproxy "$@"
    fi
    echo "tjor-proxy: neither gosu nor su-exec present — running as root (caps are dropped)" >&2
fi
exec "$@"
