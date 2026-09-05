# syntax=docker/dockerfile:1
# tjor conformance probe container: lives on the agent network and actively
# attempts what the cage must prevent. Every probe passing means every
# attempt failed.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY images/conformance/probes.py /probes.py
COPY images/conformance/echo.py /echo.py

ENTRYPOINT ["python3", "/probes.py"]
