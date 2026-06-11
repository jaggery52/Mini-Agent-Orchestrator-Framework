FROM python:3.11-slim

WORKDIR /app

# curl is used by the Docker health check
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install the package from its source layout. Copy only what the build needs
# first so the dependency layer stays cached across code-only changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# RAG corpus indexed on startup (also bind-mounted in docker-compose).
COPY knowledge_base ./knowledge_base

EXPOSE 8000

CMD ["uvicorn", "mini_agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
