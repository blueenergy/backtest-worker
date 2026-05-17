FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy local dependency packages (context = trading root)
COPY data-access-lib /deps/data-access-lib
COPY quant-strategies /deps/quant-strategies

# Install local packages
RUN pip install --no-cache-dir -e /deps/data-access-lib \
    && pip install --no-cache-dir -e /deps/quant-strategies

# Copy requirements and install
COPY backtest-worker/requirements.txt .
RUN grep -v '^-e ' requirements.txt > /tmp/requirements_filtered.txt \
    && pip install --no-cache-dir -r /tmp/requirements_filtered.txt

COPY backtest-worker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Copy application code
COPY backtest-worker/ /app

WORKDIR /app/worker

ENTRYPOINT ["/entrypoint.sh"]
