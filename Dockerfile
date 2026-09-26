# AgentForge API server image.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "uv==0.8.*"
# Docker CLI only (no daemon): used by the Docker sandbox when the host socket
# is mounted (see docker-compose.sandbox.yml and SECURITY.md).
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra all --no-install-project
COPY src ./src
COPY examples ./examples
COPY dogfood ./dogfood
RUN uv sync --frozen --no-dev --extra all

RUN useradd --create-home --uid 10001 agentforge \
    && mkdir -p /data \
    && chown agentforge:agentforge /data
USER agentforge

ENV PATH=/app/.venv/bin:$PATH \
    AGENTFORGE_DATA_DIR=/data \
    AGENTFORGE_BENCHMARKS_DIR=/app/examples/benchmarks:/app/dogfood/benchmarks

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"
CMD ["agentforge", "serve", "--host", "0.0.0.0", "--port", "8000"]
