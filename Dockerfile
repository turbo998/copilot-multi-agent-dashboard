FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# system deps: sqlite3 (already in libsqlite3-0; sqlite3 cli not strictly needed at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Create non-root user
RUN useradd -m -u 10001 appuser && \
    mkdir -p /tmp/agentdash-cache /tmp/snap && \
    chown -R appuser:appuser /app /tmp/agentdash-cache /tmp/snap
USER appuser

EXPOSE 8000

# Health check honored by Container Apps probes too
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
