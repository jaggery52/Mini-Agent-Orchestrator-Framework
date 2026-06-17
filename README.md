# Mini-Agent Orchestrator Framework

A production-style AI agent orchestrator built **from scratch — no LangChain, no LangGraph, no AutoGen.**

The agent takes a high-level user goal, breaks it into a structured plan, executes each step with real tools (document RAG, web search), and streams back a final answer over WebSocket. The whole thing runs behind per-user accounts and a browser UI, and ships with a full CI/CD pipeline to Azure.

The core design idea: **the engine is code, the agent's behaviour is configuration.** A generic state-machine engine knows nothing about planning or searching — every state, prompt, tool, and transition lives in a per-usecase JSON file. Tool routing is driven by **structured LLM output** (Pydantic schemas) rather than native tool-calling, so the entire control flow is explicit, inspectable, and deterministic.

---

## What it does

```
user goal ─▶ planner ─▶ brain (decides next tool) ─▶ tool (RAG / web search)
                            ▲                              │
                            └──────────────────────────────┘
                                   loop until ready
                                        │
                                        ▼
                                  final answer  ──▶ streamed to client
```

- **Plans** a goal into ordered steps, then executes them one tool at a time.
- **RAG** over documents the user uploads at connect time (Chroma + OpenAI embeddings).
- **Web search** via Tavily, with a DuckDuckGo fallback.
- **Per-user auth** — sign up, get a personal access token, gated WebSocket sessions (SQLite-backed).
- **Browser UI** + a CLI client, both talking the same WebSocket protocol.
- **Guardrails** for harmful requests and repeat-answer loops, implemented in prompts + routing.

## Skills demonstrated

`Python` · `FastAPI` · `WebSockets` · custom **state-machine engine** · **LLM orchestration** with structured output · **RAG** (Chroma + embeddings) · per-user auth (SQLite) · `Docker` + `nginx` load balancing · **CI/CD** (GitHub Actions → Docker Hub → Azure Container Apps)

## CI/CD pipeline

End-to-end automated delivery via two GitHub Actions workflows:

- **[`ci.yml`](.github/workflows/ci.yml)** — on every push and PR: installs the package, runs `ruff` lint and the `pytest` graph-integrity suite.
- **[`docker-publish.yml`](.github/workflows/docker-publish.yml)** — on `main` and version tags: builds the image and pushes it to **Docker Hub**; then, on `main`, logs into **Azure** and rolls the **Azure Container App** to the new image (scale-to-zero, so no idle cost).

All credentials are injected from GitHub Secrets — nothing sensitive lives in the repo.

## Architecture in brief

- The engine — [`engine/state_machine.py`](src/mini_agent/engine/state_machine.py) — is fully generic: it executes states and evaluates transitions, nothing more.
- Each agent is one folder: `src/mini_agent/configs/<usecase>/state_machine_config.json` (states, prompts, tool catalogue, routing).
- **Adding a tool = 3 small steps:** write a handler method, add a state + router branch in JSON, add the tool name to the brain's output schema. No framework plumbing.
- Two usecases ship out of the box: `tour_agency` (travel planner) and `document_helper` (document Q&A).
- Keys and KB documents are supplied **per session by the client** — the server holds no LLM keys and bakes in no knowledge base.

## Quick start

**Docker (server + browser UI):**

```bash
docker compose build           # plain build — no keys, no baked KB
docker compose up -d           # 2 app instances (shared SQLite) + nginx LB on :80
# open http://localhost/ → create an account → use the agent UI
```

**Local development:**

```bash
pip install -e ".[dev]"        # install package + dev deps
python -m mini_agent           # run WebSocket + HTTP server on :8000
pytest                         # graph-integrity tests (no network / no LLM calls)
ruff check .                   # lint

# CLI client (create an account first, then pass your token):
python clients/cli_client.py --docs examples/corpora/tour-packages.txt
```

## Tech stack

Python 3.11 · FastAPI · Uvicorn · WebSockets · OpenAI SDK · Pydantic · ChromaDB · Tavily · Docker · nginx · Azure Container Apps

## Project structure

```
src/mini_agent/
  engine/        # generic state-machine engine + state memory
  states/        # state implementations (brain, planner, tools, RAG, search, lifecycle)
  configs/       # per-usecase JSON state machines (tour_agency, document_helper)
  models/        # Pydantic schemas for structured LLM output
  db/            # SQLite user accounts + tokens
  server.py      # FastAPI app: WebSocket /ws, account API, UI pages
clients/         # web UI + CLI client
deploy/          # Dockerfile + nginx config
.github/         # CI and Docker-publish/deploy workflows
```
