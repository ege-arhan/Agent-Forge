# Default image for agent sandboxes: Python plus common developer tools.
# Build: docker build -f docker/sandbox.Dockerfile -t agentforge-sandbox:latest .
# Use:   sandbox: {kind: docker, image: agentforge-sandbox:latest}
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git make ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.* \
    && git config --system safe.directory '*'

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
