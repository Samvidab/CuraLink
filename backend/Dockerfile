# CuraLink API only (FastAPI + voice WebSocket). The frontend is served by Vercel.
# Built on the Vultr server by deploy/vultr/docker-compose.yml.
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY sample_data/ /app/sample_data/
RUN useradd --create-home --uid 10001 curalink && mkdir -p /data/secrets && chown -R curalink /data
USER curalink
ENV ENVIRONMENT=production \
    DATABASE_URL=sqlite:////data/curalink.db \
    SECRETS_DIR=/data/secrets \
    COOKIE_SECURE=true \
    PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"
# One worker: SQLite has a single writer and voice tickets live in process memory.
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
