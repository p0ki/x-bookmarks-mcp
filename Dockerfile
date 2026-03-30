# Stage 1: Install dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Create non-root user
RUN groupadd --system appuser && \
    useradd --system --gid appuser --create-home appuser

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy source code
COPY src/ ./src/
COPY config.yaml ./config.yaml

# Create data directories
RUN mkdir -p data/exports && chown -R appuser:appuser data

USER appuser

ENTRYPOINT ["python", "-m", "src.server"]
