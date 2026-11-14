FROM python:3.12-slim

WORKDIR /app

# Copy the service (pure stdlib — no pip install needed)
COPY analyze.py store.py scheduler.py recheck.py server.py ./
COPY assets/ ./assets/
COPY seed.json providers.json tips.json channels.json profiles.json ./
# Per-domain seed libraries (versioned, domain-scoped prospect lists)
COPY seeds/ ./seeds/
# Maintenance / self-test tooling
COPY tools/ ./tools/

# Persistent data (pool / schedule) — mount a Fly volume at /app/data
VOLUME ["/app/data"]

ENV PYTHONUNBUFFERED=1
EXPOSE 8787

# Bind 0.0.0.0 so Fly's proxy can reach the service; loopback would be unreachable.
CMD ["python3", "server.py", "--host", "0.0.0.0", "--port", "8787"]