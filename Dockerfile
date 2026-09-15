# ── Stage 1: Backend ──────────────────────────────────────────────────────
FROM python:3.12-slim AS backend

WORKDIR /app

# Install Python dependencies first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy full source tree
COPY src/ src/
COPY scripts/ scripts/
COPY tests/ tests/

# Ensure the project root is importable
ENV PYTHONPATH=/app

# Env defaults for offline demo
ENV DEMO_MODE=true
ENV WATSONX_ENABLED=false
ENV NETWORK_REQUIRED=false
ENV APP_PORT=8000

EXPOSE 8000

CMD ["uvicorn", "src.app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]


# ── Stage 2: Frontend ─────────────────────────────────────────────────────
FROM node:18-slim AS frontend

WORKDIR /app

# Install Node dependencies first (cache layer)
COPY src/web/package.json src/web/package-lock.json ./
RUN npm ci

# Copy frontend source
COPY src/web/ .

EXPOSE 5173

CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "5173"]
