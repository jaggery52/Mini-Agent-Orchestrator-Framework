# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

WORKDIR /app

# curl is used by the Docker health check
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install the package from its source layout. Copy only what the build needs
# first so the dependency layer stays cached across code-only changes.
# Editable install keeps the package rooted at /app/src so settings.py resolves
# PROJECT_ROOT to /app (CHROMA_DIR=/app/chroma_db, created on demand at runtime).
# No KB is baked in — each session's KB is built from the client's uploaded docs.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# Self-contained browser UI (login / create-account / index), served by the app
# (see server.py). Only clients/web is needed; the CLI client under clients/ is not.
COPY clients/web ./clients/web

# User-account DB lives here (USERS_DB_PATH=/app/data/users.db); mount a volume so
# accounts persist across restarts. Created on demand, but make the dir up front.
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "mini_agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
