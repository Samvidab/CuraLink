# CuraLink: one container = FastAPI API + voice WebSocket + built React frontend (same origin).
# Build:  docker build -t curalink .
# Run:    see docs/DEPLOYMENT.md (needs a persistent volume at /data and production env vars).

FROM node:22-slim AS web
WORKDIR /app/frontend
RUN corepack enable && corepack prepare pnpm@10.34.3 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY --from=web /app/frontend/dist /app/frontend/dist
RUN useradd --create-home curalink && mkdir -p /data && chown curalink /data
USER curalink
ENV ENVIRONMENT=production \
    FRONTEND_DIST=/app/frontend/dist \
    DATABASE_URL=sqlite:////data/curalink.db \
    COOKIE_SECURE=true \
    PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
