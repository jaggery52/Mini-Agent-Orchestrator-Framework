# Mini-Agent Orchestrator Framework

An AI agent that takes a high-level user goal, breaks it into a structured plan, executes each step using real tools, and delivers a final answer — **without any agent framework** (no LangChain, no LangGraph, no AutoGen).

Tool routing is intentionally **not** implemented via OpenAI's native tool-calling API. Instead, every decision is driven by **structured output** (Pydantic schemas) combined with explicit state context passed through `StateMemory`. This keeps the control flow fully visible and deterministic: the LLM declares what it wants to do next, the state machine routes it, and all intermediate state is inspectable at every step.

---

## Design Philosophy

The framework is built on one core idea: **the agent's behaviour is configuration, the engine is code.** The state machine engine (`engine/state_machine.py`) knows nothing about planning, searching, or answering — it only knows how to execute states and evaluate transitions. Everything that makes this particular agent a *orchestrator assistant* lives in a single JSON file: `src/mini_agent/configs/default/state_machine_config.json`.

This separation was adopted deliberately, for three reasons:

### 1. The conversation flow is editable without touching code

Every state, transition, prompt, and tool description is declared in the JSON config. Want the agent to skip the planner for simple queries? Re-route `human_input → the brain` directly. Want a confirmation step before every web search? Insert a `collect_human_input` state in front of `Internet Search Handler`. Want a different personality or stricter guardrails? Edit `agent_setup_prompt` or `analyze_instructions_prompt` in the config. None of these changes require modifying Python code — the engine reads whatever graph you give it.

In practice, changing the agent can be as simple as swapping files: the state-machine config and the indexed knowledge-base document. This repo includes example flows in `examples/`:

- `examples/configs/mini_agent.json` + `examples/corpora/mini-agent-doc.txt` — a general mini-agent/document-helper setup.
- `examples/configs/tour_agent.json` + `examples/corpora/tour-packages.txt` — a travel-agent tour-planning setup.

To try one, copy the example config content into `src/mini_agent/configs/default/state_machine_config.json`, replace the document in `knowledge_base/` with the matching `.txt` file, then rebuild/restart Docker. The same Python engine will boot with the new prompts, routing, tools, and knowledge base.

### 2. Adding a new tool takes three small steps

Tools are plain Python methods resolved by name via `getattr()`, so there is no registry, decorator, or framework plumbing:

1. **Write the handler** — add a method to `ToolStates` (`src/mini_agent/states/ai/tool_states.py`) that reads its query from brain parameters and writes its result with `StateMemory.updateToolOutput(...)`.
2. **Declare the state** — add one entry to `state_machine_config.json` (function name + args + `nextState: "the brain"`) and one branch in `tool_router`.
3. **Tell the brain it exists** — add the tool name to the `Literal` in `src/mini_agent/models/brain_output.py` and a one-line description to `available_tools` in the config.

The brain automatically starts considering the new tool on its next decision — its system prompt is assembled from the config's tool catalogue at runtime.

### 3. The same engine serves entirely different use cases

A new agent (document helper, ops bot, project planner, customer-support triage…) is a new folder under `src/mini_agent/configs/<usecase>/` with its own `state_machine_config.json` — different states, prompts, tools, and routing — passed to `StateMachine("<usecase>")`. The engine, memory model, session handling, and server are reused unchanged. Domain-specific behaviour never leaks into the core. Note: the config name is hardcoded in `server.py` for simplicity, but could easily be made dynamic.

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
| `RAG_search` | Questions answerable from local documents | ChromaDB + OpenAI `text-embedding-3-small` |
| `collect_human_input` | Ambiguous requests, or asking for the next query after an answer | WebSocket `follow_up_question` event |
| `the_planner` | Current plan is outdated or wrong | New planner call with `replan_instructions` |
| `ready_for_answer` | Enough info gathered → generate response | OpenAI completion (`DEFAULT_MODEL`, default `gpt-4.1-mini`) |
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

## Quick Start — Docker + Browser UI

```bash
# Create the env file first, then fill in OPENAI_API_KEY.
# TAVILY_API_KEY is optional; DuckDuckGo is used as a fallback if omitted.
cp .env.example .env

# Build and start two service instances + nginx load balancer.
docker compose up --build

# Or run detached.
docker compose up --build -d
```

Open `clients/web/index.html` directly in a browser (**no build step**).

The browser UI shows planner steps, brain reasoning, tool activity, follow-up questions, and final answers in a chat-style layout.

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
# Python 3.11+. Create the env file and fill in OPENAI_API_KEY first.
cp .env.example .env

pip install -e ".[dev]"

# Start the WebSocket server (either form works):
python -m mini_agent
# or:  uvicorn mini_agent.server:app --port 8000

# Lint and test:
ruff check src tests
pytest
```

The browser UI (`clients/web/index.html`) and CLI client (`clients/cli_client.py`)
default to the Docker load balancer on port 80 — point them at `ws://localhost:8000/ws`
when running a single local server.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | **Yes** | — | OpenAI API key |
| `TAVILY_API_KEY` | No | — | Tavily web search key; DuckDuckGo is used as a fallback if omitted |
| `DEFAULT_MODEL` | No | `gpt-4.1-mini` | Model used by planner, brain, and response generator |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | OpenAI embedding model used by RAG search |
| `FORCE_REINDEX` | No | `false` | Set `true` to force the RAG index to rebuild on every startup |
| `LOG_LEVEL` | No | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`) |
| `LOG_FILE` | No | `logs/agent.log` | Log file path (overridden per-instance in Docker) |

---

The RAG knowledge base is indexed from `knowledge_base/` on first startup. Later starts reuse `chroma_db/` unless `knowledge_base/` changes or `FORCE_REINDEX=true`.

Run the CLI client script:

```bash
# Deploy docker and run the script
# Connect via the Docker load balancer on port 80.
python clients/cli_client.py
```
---

## Logging

Logs are written to `logs/`

---

## WebSocket Protocol

```
Server → Client
  {"type": "acknowledgement",    "session_id": "...", "content": "What would you like to do?"}
  {"type": "agent_thinking",     "source": "planner", "goal": "...", "plan": [...]}
  {"type": "agent_thinking",     "source": "brain",   "thought": "...", "decision": "..."}
  {"type": "agent_thinking",     "source": "tool",    "message": "..."}
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
| "How does the state memory work?" | Routes to `RAG_search` against the indexed `knowledge_base/`, then answers. |
| "Help me with my project." | Detects ambiguity and asks a focused follow-up via `collect_human_input`. |
| "Compare quantum and classical computing advances" | Runs several `internet_search` calls across multiple brain steps before answering. |
| (after an answer) a new question | Continues the same session — simple queries answer directly, complex ones replan. |
| "Stop" / "Quit" / "Bye" | Ends the session with a farewell, then `session_end`. |
| Harmful / unauthorized request | Both planner and brain refuse; no tools are run. |

A full example session — goal → plan → web search → answer → multi-turn follow-up → clean session end, with TODO tracking and prompt-cache hits — is available at [examples/transcript.md](examples/transcript.md).

---

## Current Limitations

- **Single bundled document** — `knowledge_base/sample_doc.txt` is the only indexed corpus. RAG is fully functional (ChromaDB + OpenAI embeddings); a production deployment would load a larger document set.
- **One model for all roles** — `gpt-4.1-mini` (set via `DEFAULT_MODEL`) drives the planner, brain, and response generator. A larger model can be swapped in with no code change.
- **Unbounded stored history** — `getBrainContext()` windows the brain prompt, but the full per-session history grows in memory until the session ends.
- **In-memory sessions** — a restart clears all active sessions; there is no persistence layer.
- **No auth or rate-limiting** on the WebSocket endpoint.
- **Config name is hardcoded** in `server.py` (`StateMachine("default")`).

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
- Serve multiple agent use-cases from one deployment by selecting the config per connection.

**Models & providers**
- A provider abstraction so the brain/planner can target different LLM vendors.
- Per-role model selection (a stronger model for planning, a cheaper one for answering).

**Operations & quality**
- Structured tracing (OpenTelemetry spans) for every brain call, tool invocation, and token cost.
- Authentication, rate-limiting, and per-session quotas on the WebSocket endpoint.
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
│   ├── server.py                           # WebSocket server (FastAPI) + main() entry point
│   ├── __main__.py                         # `python -m mini_agent`
│   ├── session.py                          # SessionContext + ContextVar isolation
│   ├── settings.py                         # Config, logging, project-root path anchors
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
│   └── configs/default/
│       └── state_machine_config.json       # Full state graph (states, args, transitions)
│
├── knowledge_base/
│   └── sample_doc.txt                      # RAG corpus indexed on startup
├── deploy/
│   ├── Dockerfile                          # Container image (Python 3.11-slim)
│   └── nginx.conf                          # nginx WebSocket proxy + upstream config
├── clients/
│   ├── cli_client.py                       # CLI WebSocket test client
│   └── web/index.html                      # Browser WebSocket UI (open directly, no build)
├── examples/
│   ├── configs/                            # Alternative agent configs (mini_agent, tour_agent)
│   ├── corpora/                            # Matching knowledge-base documents
│   └── transcript.md                       # Real session transcript: goal → plan → execution → result
└── tests/
    └── test_state_machine.py               # Graph-integrity checks (no network/LLM calls)
```
