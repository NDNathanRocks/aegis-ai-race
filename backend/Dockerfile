# syntax=docker/dockerfile:1.7
# ---- builder: resolve dependencies into a venv and pre-bake the embedding model ----------------------------
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 FASTEMBED_CACHE_PATH=/opt/fastembed
WORKDIR /build
RUN python -m venv /opt/venv
COPY pyproject.toml ./
# Install dependencies from pyproject.toml alone so this layer is cached until dependencies change.
RUN python -c "import tomllib; p = tomllib.load(open('pyproject.toml','rb'))['project']; print('\n'.join(p['dependencies'] + p['optional-dependencies']['pgvector']))" > requirements.txt \
 && /opt/venv/bin/pip install -r requirements.txt
# Bake bge-small-en-v1.5 (ONNX) into the image: no network access or cold-start download at runtime.
RUN /opt/venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

# ---- runtime ----------------------------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    HF_HUB_OFFLINE=1 \
    PORT=8000
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/fastembed /opt/fastembed
COPY app ./app
COPY data ./data
RUN mkdir -p /app/.cache && chown -R app:app /app /opt/fastembed
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health', timeout=3)"
# Single worker: the semantic cache and rate limiter are per-process. Scale out with Redis (REDIS_URL).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
