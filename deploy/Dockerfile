# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

WORKDIR /app

# curl is used by the Docker health check
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY clients/web ./clients/web

# User-account DB lives here (USERS_DB_PATH=/app/data/users.db); mount a volume so
# accounts persist across restarts. Created on demand, but make the dir up front.
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "mini_agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
