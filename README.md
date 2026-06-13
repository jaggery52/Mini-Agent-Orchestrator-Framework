# Mini-Agent Orchestrator Framework

An AI agent that takes a high-level user goal, breaks it into a structured plan, executes each step using real tools, and delivers a final answer — **without any agent framework** (no LangChain, no LangGraph, no AutoGen).

Tool routing is intentionally **not** implemented via OpenAI's native tool-calling API. Instead, every decision is driven by **structured output** (Pydantic schemas) combined with explicit state context passed through `StateMemory`. This keeps the control flow fully visible and deterministic: the LLM declares what it wants to do next, the state machine routes it, and all intermediate state is inspectable at every step.

---

## Design Philosophy

The framework is built on one core idea: **the agent's behaviour is configuration, the engine is code.** The state machine engine (`engine/state_machine.py`) knows nothing about planning, searching, or answering — it only knows how to execute states and evaluate transitions. Everything that makes a particular agent what it is lives in a per-usecase JSON file: `src/mini_agent/configs/<usecase>/state_machine_config.json` (e.g. `configs/tour_agency/`, `configs/document_helper/`). The usecase is selected per WebSocket connection (see [WebSocket Protocol](#websocket-protocol)).

This separation was adopted deliberately, for three reasons:

### 1. The conversation flow is editable without touching code

Every state, transition, prompt, and tool description is declared in the JSON config. Want the agent to skip the planner for simple queries? Re-route `human_input → the brain` directly. Want a confirmation step before every web search? Insert a `collect_human_input` state in front of `Internet Search Handler`. Want a different personality or stricter guardrails? Edit `agent_setup_prompt` or `analyze_instructions_prompt` in the config. None of these changes require modifying Python code — the engine reads whatever graph you give it.

In practice, adding an agent is as simple as adding one folder: a state-machine config. The knowledge base is supplied by the client at connect time, not shipped in the repo. This repo ships two usecases out of the box:

- `configs/tour_agency/` — a travel-agent tour-planning setup.
- `configs/document_helper/` — a general document-Q&A setup.

To add another usecase, create `src/mini_agent/configs/<usecase>/state_machine_config.json` and have the client select it in the `init` handshake (and upload its docs in the `documents` message — see [Knowledge Base](#knowledge-base--per-session-client-provided)). The same Python engine boots with the new prompts, routing, and tools — no code changes.

### 2. Adding a new tool takes three small steps

Tools are plain Python methods resolved by name via `getattr()`, so there is no registry, decorator, or framework plumbing:

1. **Write the handler** — add a method to `ToolStates` (`src/mini_agent/states/ai/tool_states.py`) that reads its query from brain parameters and writes its result with `StateMemory.updateToolOutput(...)`.
2. **Declare the state** — add one entry to `state_machine_config.json` (function name + args + `nextState: "the brain"`) and one branch in `tool_router`.
3. **Tell the brain it exists** — add the tool name to the `Literal` in `src/mini_agent/models/brain_output.py` and a one-line description to `available_tools` in the config.

The brain automatically starts considering the new tool on its next decision — its system prompt is assembled from the config's tool catalogue at runtime.

### 3. The same engine serves entirely different use cases

A new agent (document helper, ops bot, project planner, customer-support triage…) is a new folder under `src/mini_agent/configs/<usecase>/` with its own `state_machine_config.json` — different states, prompts, tools, and routing. The usecase is chosen per connection: the client names it in the `init` handshake, and the server constructs `StateMachine("<usecase>")` for that session. The engine, memory model, session handling, and server are reused unchanged. Domain-specific behaviour never leaks into the core.

### Why structured output instead of native tool calling

Driving every decision through structured output keeps the loop, prompts, and context handling fully explicit. The brain returns a typed Pydantic object (`BrainOutput`) stating which tool it wants, why (`decision_taken`), and the live TODO status; the state machine routes on that value with inspectable conditions. There is no hidden retry loop, no implicit message threading, no framework magic. Every hop is logged, every intermediate state can be dumped, and the whole control flow can be read in one JSON file.

---

## How the Agent Loop Works

The agent is a **JSON-configured directed state machine**. Every node is a state that maps to a Python method. Transitions are either direct or conditional.

```
Start
  ↓
human_input        (wait for user message via WebSocket)
  ↓
Planner            (LLM generates a 3–5 step TODO list; refuses harmful requests with a single end step)
  ↓
the_brain ◄──────────────────────────────────────────────────────────┐
  ↓                                                                  │
tool_router                                                          │
  ├── internet_search ────────────────────────────────────────────► ─┤
  ├── RAG_search ──────────────────────────────────────────────────► ─┤
  ├── collect_human_input ─────────────────────────────────────────► ─┤ (also used to ask "anything else?")
  ├── the_planner (replan) ───────────────────────────────────────► ──┤
  ├── ready_for_answer                                               │
  │       ↓                                                          │
  │   response_generator ──────────────────────────────────────────► ─┘  (loops back to brain after answer)
  ├── fallback_agent ───────────────► collect_human_input ────────► ─┤  (contextual follow-up after an answer)
  └── end  →  End  →  EndFinal        (user quit or harmful/illegal request)
```

The session is **persistent across turns**. After delivering an answer the flow returns to the brain. If the brain tries to answer again instead of asking what comes next, the runtime routes that loop through `fallback_agent`, which generates a contextual follow-up and then hands off to `collect_human_input`. The session only terminates when the brain selects the `end` tool.

**Core execution loop** (`engine/state_machine.py`):
```python
while currentStateName != "EndFinal":
    __execute_state()     # call state method via getattr()
    __define_next_state() # direct or condition-evaluated transition
```

**`the_planner` state** calls OpenAI and converts the user goal into a structured 3–5 step TODO list. Each step specifies which tool to call and a specific query or action.

**`the_brain` state** calls OpenAI with a `BrainOutput` Pydantic schema and decides the next tool to use:
```json
{
  "tool_to_use": "internet_search",
  "tool_parameters": {
    "query": "quantum computing breakthroughs 2025",
    "response_instructions": "Focus on practical near-term applications.",
    "follow_up_question": "Which aspect are you most interested in?",
    "replan_instructions": "User wants more depth — revise plan to add a second search.",
    "end_message": null
  },
  "decision_taken": "The user asked about recent developments. I need live information.",
  "TODO_updates": [
    {"title": "Web Search", "description": "Search for latest quantum news", "status": "in progress"},
    {"title": "Ready for Answer", "description": "Deliver compiled findings", "status": "not done"}
  ]
}
```

When the brain selects `end`, `end_message` is populated with a farewell (user quit) or a brief refusal (harmful request), which is sent to the client as a `final_response` event before `session_end`.

The brain's output is stored in **StateMemory**, the router branches to the right handler, the tool runs and appends its output to StateMemory, and the loop returns to the brain with the updated context.

---

## Tools Integrated

| Tool | Trigger | Implementation |
|------|---------|----------------|
| `internet_search` | Questions needing current/live data | Tavily API → DuckDuckGo fallback |
| `RAG_search` | Questions answerable from local documents | ChromaDB + the connection's `embedding_model` |
| `collect_human_input` | Ambiguous requests, or asking for the next query after an answer | WebSocket `follow_up_question` event |
| `the_planner` | Current plan is outdated or wrong | New planner call with `replan_instructions` |
| `ready_for_answer` | Enough info gathered → generate response | OpenAI completion with the connection's `agent_model` |
| `fallback_agent` | Internal guardrail when an answer was already delivered but the brain tries to answer again | Generates a contextual follow-up from the last answer, then routes to `collect_human_input` |
| `end` | User asks to quit, or request is harmful/illegal/unethical | Sends `end_message` then `session_end` |

---

## Simple Guardrails

The framework includes two lightweight guardrails implemented through prompts, structured output, and state-machine routing:

- **Fallback agent for repeated-answer loops** — after `response_generator` sends a final answer, `answer_delivered` is set in `StateMemory`. If the brain later chooses `ready_for_answer` again after an answer has already been delivered, `BrainStates` overrides the effective tool to `fallback_agent`. The fallback agent uses the original user query and the last delivered answer to produce a contextual follow-up question, stores it as `collect_human_input`, and keeps the session moving without regenerating the same answer.
- **Stop on harmful content** — both the Planner and Brain are instructed to check harmful, illegal, unethical, or unauthorized requests before normal planning/tool use. If detected, the agent selects `end`, writes a brief refusal into `end_message`, marks TODO items as `not relevant`, sends the refusal as `final_response`, and then emits `session_end`. No search or RAG tool is run for that request.

These guardrails are intentionally simple and inspectable: the decision is visible in the planner/brain output, the route is visible in `tool_router`, and the final stop/follow-up behavior is stored in `StateMemory`.

---

## Context Strategy

### State Memory
All agent execution state lives in `StateMemory` (isolated per session via Python `ContextVar`):
- `updated_by_the_brain` — full decision history (step N → tool + reasoning + params + TODO status)
- `updated_by_tools` — ordered outputs from each tool; the Brain context receives only the most recent entries
- `conversation_history` — chronological log of actor events (user, brain, tool, agent); agent entries include `answered_query` and `answered: true`
- `variables` — runtime variables (`agent_decision`, `user_query`, `tokenCount`, `answer_delivered`, ...)

The brain receives `getBrainContext()` — a compact snapshot with selected variables and windowed history/tool context — as its user message.

> **Conversation history** is stored for the full session and grows with each turn. The Brain context is already windowed to the last 5 entries via `BRAIN_CONTEXT_WINDOW`; in production, the stored history could also be pruned or summarised to avoid unbounded memory growth on very long sessions.

### Prompt Caching
OpenAI's **automatic prefix caching** is exploited with zero extra code:
- The `agent_setup_prompt` (~600 words) + `analyze_instructions` + tool catalogue form a static system message (≥1024 tokens).
- This prefix is **identical on every brain call** → cached after call 1 → 50% cost reduction on cached tokens.
- Cache hits are logged: `[TheBrain] Prompt cache HIT — N tokens served from cache`.

---

## Secrets — create this before deploying

The server needs exactly **one** secret: `SERVER_ACCESS_TOKEN`. There is no build-time
key — the knowledge base is built per session from client-uploaded docs, so the image
contains no LLM key and no baked KB.

| File (repo root) | Scope | Holds | Create it with |
|------------------|-------|-------|----------------|
| `.env` | **Runtime** | `SERVER_ACCESS_TOKEN` (WebSocket auth gate) | `cp .env.example .env` then set the token |

- `.env` is auto-loaded by `docker compose` to inject `SERVER_ACCESS_TOKEN`; with an empty
  token the server rejects every connection.
- **CI/CD:** set `SERVER_ACCESS_TOKEN` as a runtime env from GitHub Actions / Azure secrets.
  The Docker build needs no secret at all.

## Quick Start — Docker + Browser UI

```bash
# 1. Set the runtime secret (run from the repo root):
cp .env.example .env                          # then set SERVER_ACCESS_TOKEN

# 2. Build (no secret needed) and start two instances + nginx.
docker compose build
docker compose up -d
```

The image holds **no** KB and **no** LLM/search keys — each session builds its own
knowledge base from the documents the client uploads in the `documents` handshake.

Open `clients/web/index.html` in a browser (**no build step**). A connection dialog
prompts for your access token (= `SERVER_ACCESS_TOKEN`), OpenAI key, usecase, model
names, and the **knowledge-base files** to upload; fill them in and click **Connect**
(non-file values can be remembered in the browser).

The browser UI is a three-panel live view of the agent: an **Agent Flow** pipeline on the
left that highlights the active agent/tool node (User → Planner → Brain → tool → Answer →
End) with animated hand-offs; a **Plan & Reasoning** panel in the middle showing the
planner's structured plan as an interactive TODO checklist (statuses flip live from the
brain's `todo_updates`, with a progress bar and revision badges on replans) plus a brain
reasoning timeline; and the **chat** on the right.

Per-instance log files are written to `./logs/` on the host:
```
logs/mini-agent-1.log
logs/mini-agent-2.log
```
---

## Local Development (no Docker)

The project is a standard `src/`-layout Python package. Install it (and dev tools)
in editable mode, then run the server directly:

```bash
# Python 3.11+. Set SERVER_ACCESS_TOKEN in .env first.
cp .env.example .env

pip install -e ".[dev]"

# Start the WebSocket server (either form works). No KB build step — the server
# reads no LLM key; sessions build their KB from client-uploaded docs:
SERVER_ACCESS_TOKEN=dev-token python -m mini_agent
# or:  SERVER_ACCESS_TOKEN=dev-token uvicorn mini_agent.server:app --port 8000

# Lint and test:
ruff check src tests
pytest

# Run the CLI client (reads keys/token from its own environment; --docs uploads the KB):
SERVER_ACCESS_TOKEN=dev-token OPENAI_API_KEY=sk-... \
  python clients/cli_client.py --url ws://localhost:8000/ws --usecase tour_agency \
  --docs examples/corpora/tour-packages.txt
```

The browser UI (`clients/web/index.html`) and CLI client (`clients/cli_client.py`)
default to the Docker load balancer on port 80 — point them at `ws://localhost:8000/ws`
when running a single local server.

---

## Environment Variables

The running **server** reads only the auth/operational vars below. LLM and web-search
keys plus model names are **not** read from the environment — each client supplies them
in the `init` handshake (see [WebSocket Protocol](#websocket-protocol)).

| Variable | Scope | Required | Default | Description |
|----------|-------|----------|---------|-------------|
| `SERVER_ACCESS_TOKEN` | Server (runtime) | **Yes** | — | WebSocket auth gate — clients must present this in the `init` handshake |
| `LOG_LEVEL` | Server (runtime) | No | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`) |
| `LOG_FILE` | Server (runtime) | No | `logs/agent.log` | Log file path (overridden per-instance in Docker) |

The client supplies these per connection (see `clients/cli_client.py` flags / env):
`SERVER_ACCESS_TOKEN`, `OPENAI_API_KEY` (LLM + embeddings), optional `TAVILY_API_KEY`,
`DEFAULT_MODEL`, `EMBEDDING_MODEL`, `USECASE`, and the `--docs` files to upload.

---

## Knowledge Base — per-session, client-provided

There is **no** build-time indexing and **no** corpus shipped in the repo. After `init`,
the client sends a `documents` message with its `.txt`/`.md` files; the server writes them
to a per-session temp folder, indexes them into a Chroma collection named by the session id
(using the client's own embedding key), and replies `kb_ready`. The collection is built
**once** and reused by every `RAG_search` query, then deleted — along with the temp folder —
when the connection closes. The server holds no embedding key and persists no KB across
sessions. `examples/corpora/*.txt` are sample docs you can upload to try it.

---

## Logging

Logs are written to `logs/`

---

## WebSocket Protocol

The connection is gated by a two-step handshake. Immediately after connecting, the client
must send an `init` message (auth token, LLM/search keys, model names, usecase), then a
`documents` message carrying the `.txt`/`.md` files that make up **this session's** knowledge
base. The server validates the token and usecase, then builds a per-session Chroma collection
from the uploaded docs using the client's own key, replies with `kb_ready`, and only then
accepts queries. On any failure it sends an `error` and closes with code **4001**. The server
holds no LLM/search keys of its own and ships with no baked KB — keys and docs both arrive
per connection, and the session's collection is deleted when the connection ends.

```
Client → Server (FIRST message, required)
  {"type": "init",
   "token": "<SERVER_ACCESS_TOKEN>",
   "usecase": "tour_agency",
   "collection_name": "tour_agency",     // accepted but overridden by a per-session name
   "openai_api_key": "sk-...",
   "tavily_api_key": "tvly-...",          // optional; DuckDuckGo fallback if empty
   "agent_model": "gpt-4.1-mini",
   "embedding_model": "text-embedding-3-small"}

Client → Server (SECOND message, required)
  {"type": "documents",
   "files": [{"name": "guide.txt", "content": "..."}, ...]}   // combined ≤ 2 MB

Server → Client
  {"type": "kb_ready",           "chunks": 11}   // KB built; queries now accepted
  {"type": "acknowledgement",    "session_id": "...", "content": "What would you like to do?"}
  {"type": "agent_thinking",     "source": "planner", "goal": "...", "replan": false,
                                 "plan": [{"title": "...", "description": "...", "tool": "RAG_search"}, ...]}
  {"type": "agent_thinking",     "source": "brain",   "step": "step 2", "thought": "...",
                                 "decision": "...", "tool": "internet_search",
                                 "todo_updates": [{"title": "...", "description": "...", "status": "in progress"}, ...]}
  {"type": "agent_thinking",     "source": "tool",    "tool": "RAG_search", "message": "..."}
  {"type": "follow_up_question", "content": "..."}
  {"type": "final_response",     "content": "..."}
  {"type": "session_end",        "status": "successful"}
  {"type": "error",              "content": "..."}

Client → Server
  {"type": "human_input", "content": "..."}
```

### Endpoints

| Endpoint | Protocol | Description |
|----------|----------|-------------|
| `GET /health` | HTTP | Load balancer health check — returns `{"status": "ok"}` |
| `WS /ws` | WebSocket | One connection = one agent session |

---

## Example Interactions

| Input | What the agent does |
|-------|---------------------|
| "What is the capital of France?" | Plans, then answers directly in a single brain call — no tools needed. |
| "What happened in AI this week?" | Routes to `internet_search` (Tavily, with sources), then answers. |
| "How does the state memory work?" | Routes to `RAG_search` against the connection's usecase collection, then answers. |
| "Help me with my project." | Detects ambiguity and asks a focused follow-up via `collect_human_input`. |
| "Compare quantum and classical computing advances" | Runs several `internet_search` calls across multiple brain steps before answering. |
| (after an answer) a new question | Continues the same session — simple queries answer directly, complex ones replan. |
| "Stop" / "Quit" / "Bye" | Ends the session with a farewell, then `session_end`. |
| Harmful / unauthorized request | Both planner and brain refuse; no tools are run. |

A full example session — goal → plan → web search → answer → multi-turn follow-up → clean session end, with TODO tracking and prompt-cache hits — is available at [examples/transcript.md](examples/transcript.md).

---

## Current Limitations

- **Per-session upload cap** — the client uploads its KB docs each session (capped at `MAX_DOCS_BYTES`, ~2 MB combined). RAG is fully functional (ChromaDB + OpenAI embeddings); sample docs live under `examples/corpora/`. A production deployment might raise the cap or add chunked upload for larger corpora.
- **One model for all roles** — the client-supplied `agent_model` drives the planner, brain, and response generator. A larger model can be selected per connection with no code change.
- **Unbounded stored history** — `getBrainContext()` windows the brain prompt, but the full per-session history grows in memory until the session ends.
- **In-memory sessions** — a restart clears all active sessions; there is no persistence layer.
- **Shared-secret auth** — the WebSocket is gated by a single `SERVER_ACCESS_TOKEN`; there is no per-user identity, rate-limiting, or JWT/expiry yet.
- **Client holds the keys** — LLM/search keys travel in the `init` message, so clients are trusted. Use TLS (`wss://`) in production and treat the browser UI's inline keys accordingly.

---

## Roadmap / Future Enhancements

**Context & memory**
- Token-budget-aware pruning or rolling summarisation of older history and tool outputs.
- Pluggable memory backends (Redis / Postgres) for session persistence and resume-on-reconnect.

**Knowledge & tools**
- A `/upload` endpoint for dynamic document ingestion and re-indexing.
- Richer RAG: hybrid (keyword + vector) search, re-ranking, and per-source citations.
- More built-in tools (database/SQL query, calculator, file reader, internal API callers) plus a typed tool-registration helper to reduce the manual three-step wiring.

**Configuration & multi-agent**
- Load the state-machine config from a database or API so flows can change without a restart.
- JSON-Schema validation of configs, and a visual graph viewer/editor for the state machine.
- ✅ Serving multiple usecases from one deployment by selecting the config per connection (done — `tour_agency`, `document_helper`).

**Models & providers**
- A provider abstraction so the brain/planner can target different LLM vendors.
- Per-role model selection (a stronger model for planning, a cheaper one for answering).

**Operations & quality**
- Structured tracing (OpenTelemetry spans) for every brain call, tool invocation, and token cost.
- Token auth on the WebSocket is in place (`SERVER_ACCESS_TOKEN` in the `init` handshake); still to add: per-user identity (JWT/expiry), rate-limiting, and per-session quotas.
- A CI/CD pipeline (lint → test → build → publish image) wired to the existing `ruff` / `pytest` / Docker targets.
- Expanded automated test coverage: tool handlers, memory windowing, and an end-to-end session simulation against a mocked LLM.

---

## Project Structure

```
mini-agent-framework/
├── pyproject.toml                          # Packaging, deps, console script, ruff/pytest config
├── docker-compose.yml                      # Two service instances + nginx load balancer
├── README.md                               # This file
├── .env.example                            # Environment variable template
│
├── src/mini_agent/                         # The installable package
│   ├── server.py                           # WebSocket server (FastAPI) — init/documents handshake + main()
│   ├── __main__.py                         # `python -m mini_agent`
│   ├── session.py                          # SessionContext (per-connection keys/usecase/KB) + ContextVar isolation
│   ├── settings.py                         # SERVER_ACCESS_TOKEN, logging, project-root path anchors
│   ├── engine/
│   │   ├── state_machine.py                # Core execution engine
│   │   └── state_memory.py                 # Session state store (ContextVar-isolated)
│   ├── models/
│   │   ├── brain_output.py                 # Pydantic BrainOutput + ToolParameters (includes end_message)
│   │   └── planner_output.py               # Pydantic PlannerOutput + TODOItem (tool field includes end)
│   ├── states/
│   │   ├── custom_states.py                # Extension point: LifeCycleStates + BrainStates + ToolStates
│   │   ├── custom_conditions.py            # Extension point: inherits UtilsConditions
│   │   ├── lifecycle_states.py             # start, end, condition_check, collect_human_input
│   │   ├── conditions/
│   │   │   └── utils_conditions.py         # check_global_variable() — routes tool_router
│   │   └── ai/
│   │       ├── brain_states.py             # the_brain() state function
│   │       ├── tool_states.py              # internet_search, RAG_search, response_generator, the_planner
│   │       ├── llm/                        # OpenAI calls (renamed from `openai/` to avoid shadowing the SDK)
│   │       │   ├── the_brain.py            # Structured-output call (brain)
│   │       │   ├── the_planner.py          # Structured-output call (planner)
│   │       │   ├── response_generator.py
│   │       │   └── fallback_agent.py
│   │       └── search/
│   │           ├── internet_search.py      # Tavily + DuckDuckGo fallback
│   │           └── rag_search.py           # ChromaDB RAG (500-word chunks, 150-word overlap)
│   └── configs/                            # One folder per usecase (selected per connection)
│       ├── tour_agency/state_machine_config.json
│       └── document_helper/state_machine_config.json
│
├── deploy/
│   ├── Dockerfile                          # Container image (plain build — no secret, no baked KB)
│   └── nginx.conf                          # nginx WebSocket proxy + upstream config
├── clients/
│   ├── cli_client.py                       # CLI WebSocket test client (--docs uploads the KB)
│   └── web/index.html                      # Browser WebSocket UI (open directly, no build)
├── examples/
│   ├── configs/                            # Alternative agent configs (mini_agent, tour_agent)
│   ├── corpora/                            # Sample docs to upload as a session KB
│   └── transcript.md                       # Real session transcript: goal → plan → execution → result
└── tests/
    └── test_state_machine.py               # Graph-integrity checks (no network/LLM calls)
```
