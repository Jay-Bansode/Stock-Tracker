# Single-container image for free web hosting (RUN_MODE=cron): the API also serves the
# dashboard, and an external scheduler calls /api/cron/poll every minute. Build context: repo root.

FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Kolkata \
    RUN_MODE=cron \
    FRONTEND_DIST=/app/static

WORKDIR /app
COPY backend/pyproject.toml ./
RUN python -c "import tomllib, subprocess, sys; \
deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; \
subprocess.check_call([sys.executable, '-m', 'pip', 'install', *deps])"

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
RUN python -m app.marketdata.upstox.proto
COPY --from=web /web/dist ./static

RUN useradd --create-home --uid 10001 tracker
USER tracker

# Render (and most hosts) inject PORT. Migrations are idempotent, so running them on every
# start keeps the database schema in step with each deploy.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
