# syntax=docker/dockerfile:1
# tjor egress proxy: pinned mitmproxy base + the policy addon.
# BASE_IMAGE is default-less on purpose (charter L8): the launcher supplies
# the digest-pinned reference from config/tjor.toml.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY proxy/addon.py python/tjor_policy.py /addon/

ENV TJOR_POLICY_FILE=/policy/policy.toml
