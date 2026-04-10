# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Incident Cortex is a ReAct tool-calling pipeline with 10 tools/agents that triages SRE incidents end-to-end. It takes raw incident reports (text, Slack messages, form submissions, log file attachments, or screenshots), runs them through a Claude-driven tool loop, and produces severity assessments, root cause hypotheses, Jira tickets, and notifications — all in ~15 seconds. The orchestration pattern is ReAct (Reasoning + Acting) via the Anthropic Messages API, replacing the original LangGraph StateGraph.

## Running the System

```bash
# Start all services (first run takes ~5-10 min for codebase indexing)
docker compose up -d
docker compose logs indexer -f   # wait for "Indexing complete"

# Access points:
# UI: http://localhost:3000
# API + docs: http://localhost:8000/docs
# MailHog: http://localhost:8025
# Jira Mock: http://localhost:8081 (browse tickets)
# Slack Mock: http://localhost:8090
# Langfuse tracing: http://localhost:3001
```

Requires `.env` with `ANTHROPIC_API_KEY`. Copy `.env.example` to start. `OPENAI_API_KEY` is optional — falls back to Sentence Transformers for embeddings.

## Testing

```bash
# All tests (inside Docker)
docker compose exec backend pytest -v

# Single test file
docker compose exec backend pytest tests/agents/test_intake.py -v

# With coverage
docker compose exec backend pytest --cov=agents tests/
```

## Architecture

### Agent Pipeline (`backend/app/agents/`)

The pipeline is a **ReAct tool-calling loop** defined in `orchestrator.py`. Claude (`claude-sonnet-4-6`) receives the incident and autonomously decides which tools to call, in what order, and whether to run them in parallel — up to 15 iterations.

**Tool execution flow:**
1. `parse_incident` — always first (sequential)
2. Parallel fan-out (single Claude turn, dispatched via `asyncio.gather`):
   - `search_codebase` — always
   - `check_duplicates` — always
   - `query_metrics` — always (if service name known)
   - `analyze_logs` — only if log/text attachments present
   - `analyze_images` — only if image attachments present
3. `synthesize_triage` — after all parallel results are in
4. `escalate_p1` — only if severity == P1
5. `create_ticket` — skipped if confirmed duplicate
6. `send_notifications` — always last

Key behavioral rules:
- P1 + confidence < 0.5 → auto-degrades to P2, sets `needs_human_review=True`
- Dedup similarity ≥ 0.85 → skips ticket creation, links to existing incident
- Insufficient info → clarification email sent, pipeline stops
- **WebSocket**: browser must connect directly to `ws://localhost:8000/ws/{id}` — CRA dev proxy does NOT forward WS upgrades.

### State Model

All agent state flows through a shared mutable `dict` passed by reference to each tool handler. Handlers read from state and write back to disjoint keys, making parallel execution safe without locks. Key state keys:
- `parsed_incident` — output of `parse_incident` tool
- `code_analysis` — output of `search_codebase` tool
- `dedup_result` — output of `check_duplicates` tool
- `triage_verdict` — output of `synthesize_triage` tool
- `log_analysis` — output of `analyze_logs` tool (if invoked)
- `image_analysis` — output of `analyze_images` tool (if invoked)
- `metrics_result` — output of `query_metrics` tool

Pipeline state is also persisted to PostgreSQL via `EventStore` after every tool call for WebSocket replay and audit.

### Services (`backend/app/services/`)

- `vector_store.py` — ChromaDB client wrapper (host: `chromadb:8001` in Docker, collection: `ecommerce_codebase`)
- `event_store.py` — PostgreSQL-backed event log for pipeline state persistence and WebSocket streaming
- `llm_client.py` — Anthropic/OpenRouter client; uses `anthropic_api_key` by default

### API (`backend/app/api/`)

- `routes.py` — REST endpoints under `/api` (incident submission, status retrieval)
- `websocket.py` — WebSocket endpoint at `/ws/incidents/{id}` for real-time pipeline updates

### Frontend (`frontend/src/`)

React 18 with JSX (no TypeScript despite README). Key components:
- `IncidentForm.jsx` — report submission form
- `IncidentList.jsx` — incident history
- `TriageView.jsx` — displays the triage document
- `App.jsx` — top-level routing

Communicates with backend via REST + WebSocket. `REACT_APP_API_URL` controls the backend URL.

### Indexer (`indexer/index_codebase.py`)

One-shot container that clones `ecommerce_repo_url` (default: reaction-commerce) and indexes it into ChromaDB. Controlled by `CODEBASE_PATH` env var. Runs once on startup (`restart: "no"`). To re-index: `docker compose down -v && docker compose up -d`.

### Observability

Langfuse is wired in for LLM tracing (port 3001). Requires `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in `.env` to enable; works without them in degraded mode.

## Key Configuration (`backend/app/config.py`)

| Setting | Default | Notes |
|---------|---------|-------|
| `CHROMA_HOST` / `CHROMA_PORT` | `chromadb` / `8001` | ChromaDB lives at 8001 internally (mapped from 8000) |
| `DEDUP_SUGGESTION_THRESHOLD` | `0.85` | Flags as possible duplicate |
| `DEDUP_DUPLICATE_THRESHOLD` | `0.95` | Routes to link_existing instead of create ticket |
| `OPENROUTER_MODEL` | `google/gemini-flash-1.5` | Alternative LLM path via OpenRouter |

Note: `docker-compose.yml` maps ChromaDB's internal port 8000 to host port 8001, so `chroma_port` in config is `8001`.
