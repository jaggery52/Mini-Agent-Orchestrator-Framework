# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

WORKDIR /app

# curl is used by the Docker health check
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install the package from its source layout. Copy only what the build needs
# first so the dependency layer stays cached across code-only changes.
# Editable install keeps the package rooted at /app/src so settings.py resolves
# PROJECT_ROOT to /app (KNOWLEDGE_BASE_DIR=/app/knowledge_base, CHROMA_DIR=/app/chroma_db)
# — consistent for the build-time index below and runtime queries.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# RAG corpora — one sub-directory per usecase (collection name == sub-dir name).
COPY knowledge_base ./knowledge_base

# Build every usecase's Chroma collection at BUILD time and bake it into the image.
# The embedding key is provided as a BuildKit secret and never lands in the image
# layers or the runtime environment. Build with:
#   DOCKER_BUILDKIT=1 docker build --secret id=openai_key,src=./openai_key.txt \
#       -f deploy/Dockerfile -t mini-agent .
ARG EMBEDDING_MODEL=text-embedding-3-small
RUN --mount=type=secret,id=openai_key \
    OPENAI_API_KEY="$(cat /run/secrets/openai_key)" \
    EMBEDDING_MODEL="${EMBEDDING_MODEL}" \
    python -m mini_agent.build_kb

EXPOSE 8000

CMD ["uvicorn", "mini_agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
