# ShopMCP: one image serving the API, MCP endpoint, PayPal redirects and the
# built React frontend (same origin, so no CORS or second service needed).
# Build locally:  docker build -t shopmcp .
# Run locally:    docker run --rm -p 8000:10000 --env-file .env shopmcp

# ---- 1. build the frontend ----
# Debian-based (not Alpine): Vite's and TypeScript's native binaries need glibc.
FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. Python runtime ----
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Serve the built frontend from FastAPI (see app/config.py).
    FRONTEND_DIST=/app/frontend/dist \
    # SQLite db + uploaded photos. On Render a persistent disk is mounted here;
    # anything outside it is wiped on every deploy.
    DATA_DIR=/var/data
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist /app/frontend/dist

# Render sets PORT (default 10000). --timeout-graceful-shutdown: an open MCP
# client stream must not block shutdown/redeploys forever.
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --timeout-graceful-shutdown 3"]
