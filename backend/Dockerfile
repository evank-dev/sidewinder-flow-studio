# ── Flow Studio Backend ───────────────────────────────────────────────────────
# Python 3.13 slim — production-ready image
FROM python:3.13-slim

# System deps needed by some SQLAlchemy drivers + matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the full application, then install it as a regular (non-editable)
# package. A regular install reliably resolves and installs every dependency
# declared in pyproject.toml; editable (-e) installs are for local dev and can
# behave inconsistently inside containers.
COPY . .
RUN pip install --no-cache-dir .

# httpx is sometimes skipped by pip's resolver as "already satisfied" in slim
# base images even though it's not actually importable. Force it explicitly so
# the module is guaranteed present.
RUN pip install --no-cache-dir --force-reinstall --no-deps "httpx>=0.27.0" \
    && python -c "import httpx; print('httpx', httpx.__version__, 'OK')"

# Optional: install additional DB drivers or enterprise engines, e.g.:
# RUN pip install --no-cache-dir ".[enterprise,snowflake,bigquery]"

# Create data directories
RUN mkdir -p /data/projects /data/frame_cache /data/reports_data

# Non-root user for security
RUN useradd -m -u 1000 flowstudio && chown -R flowstudio:flowstudio /app /data
USER flowstudio

EXPOSE 8000

# Environment overrides — set these in docker-compose or at runtime
ENV HOST=0.0.0.0 \
    PORT=8000 \
    DEBUG=false \
    PROJECTS_DIR=/data/projects \
    FRAME_CACHE_DIR=/data/frame_cache \
    METADATA_DB_URL=sqlite+aiosqlite:////data/flow_studio.db

CMD ["python", "main.py"]
