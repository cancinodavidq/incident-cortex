# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Incident Cortex is a 6-agent LangGraph pipeline that triages SRE incidents end-to-end. It takes raw incident reports (text, Slack messages, or form submissions), runs them through a structured agent workflow, and produces severity assessments, root cause hypotheses, Jira tickets, and notifications — all in ~15 seconds.

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

The pipeline is a LangGraph `StateGraph` defined in `orchestrator.py`. All agent state flows through `IncidentState` (a `TypedDict` in `models/incident.py`).

Flow: **intake** → [**code_analysis** ‖ **dedup**] → **join_analysis** → **triage_synth** → (**escalate**?) → **ticket** → **notify**

- Code analysis and dedup run **in parallel** via LangGraph `Send()`.
- After `triage_synth`: P1 severity routes to `escalate` (fast-path, pages oncall), then proceeds to `ticket`.
- After `triage_synth`: if dedup similarity ≥ 0.85, routes to `notify` (skips ticket creation) to link against existing duplicate.
- If intake determines the report lacks sufficient info, routes to `request_clarity` and ends.
- `triage_verdict` now includes `runbook` (list of structured remediation steps with commands) and `suggested_assignee_team`.
- **WebSocket**: browser must connect directly to `ws://localhost:8000/ws/{id}` — CRA dev proxy does NOT forward WS upgrades.

### State Model (`models/incident.py`)

Agents communicate exclusively through `IncidentState`. Each agent reads from state and returns a dict that gets merged back. Key fields:
- `parsed_incident` — output of intake agent (matches `ParsedIncident`)
- `code_analysis` — output of code analysis agent (matches `CodeAnalysis`)
- `dedup_result` — output of dedup agent (matches `DedupResult`)
- `triage_verdict` — output of synthesizer (matches `TriageVerdict`)

`TriageVerdict` has a built-in coherence rule: P1 with confidence < 0.5 auto-degrades to P2 + sets `needs_human_review = True`.

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
