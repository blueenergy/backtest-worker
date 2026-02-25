FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy requirements (minus the editable local deps, which come via volume mounts)
COPY requirements.txt .
RUN grep -v '^\-e ' requirements.txt > /tmp/requirements_filtered.txt \
    && pip install --no-cache-dir -r /tmp/requirements_filtered.txt

# Install local editable packages (source mounted at runtime, but we need them on PYTHONPATH)
# They will be installed in editable mode from mounted volumes at container start via entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Copy application code
COPY . /app

WORKDIR /app/worker

ENTRYPOINT ["/entrypoint.sh"]
