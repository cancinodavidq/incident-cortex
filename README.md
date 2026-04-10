# Incident Cortex

> SRE Incident Triage Agent — AgentX Hackathon 2026

**What it does in one sentence:** Incident Cortex reads an incident report, searches your codebase, checks live metrics, analyzes attached logs and screenshots, deduplicates against past incidents, and delivers a severity verdict + runbook + Jira ticket + notifications in ~15 seconds — a task a senior SRE would spend 20–30 minutes doing manually.

---

## The Problem

When an incident fires at 2 AM, the on-call engineer faces a cold-start problem: raw alert text, no context, and a codebase they may not own. They spend the first 20–30 minutes doing triage manually — searching code, checking dashboards, scanning for duplicates, writing a ticket — before they can start fixing. That delay is expensive. For a P1 outage at $50K/hour revenue impact, 20 minutes of triage costs ~$17K before a single remediation command runs.

## The Solution

Incident Cortex replaces that cold-start triage with an autonomous ReAct agent loop. The output is not a classification label. It is the document a senior SRE would produce after 30 minutes of investigation: specific file paths, exact shell commands in a runbook, a confidence-calibrated severity, and a pre-filled ticket — ready to act on in seconds.

---

## How It Works

Incident Cortex uses the **ReAct (Reasoning + Acting)** pattern via Claude's native tool use API. A single `claude-sonnet-4-6` instance drives the entire pipeline by issuing tool calls autonomously. No hardcoded routing graph — Claude decides what to investigate and in what order based on the incident content.

```
Incident Submission (text / log files / screenshots)
              │
              ▼
    ┌─────────────────────┐
    │  Turn 1 (sequential)│
    │   parse_incident     │  Extracts structure from raw text + vision on images
    └──────────┬──────────┘
               │
    ┌──────────▼──────────────────────────────────────────┐
    │          Turn 2 (parallel fan-out — asyncio.gather) │
    │                                                     │
    │  search_codebase   ← semantic RAG on your codebase  │
    │  check_duplicates  ← vector similarity vs history   │
    │  query_metrics     ← error rate, p95 latency, mem   │
    │  analyze_logs*     ← Haiku reads attached .log files│
    │  analyze_images*   ← Haiku vision on screenshots    │
    │                                                     │
    │  (* conditional: only called if attachments exist)  │
    └──────────┬──────────────────────────────────────────┘
               │
    ┌──────────▼──────────┐
    │  synthesize_triage  │  P1-P4 + confidence + root cause + runbook
    └──────────┬──────────┘
               │
      ┌────────┴──────────────────────┐
      │ P1?                           │ duplicate (similarity ≥ 0.85)?
      ▼                               ▼
  escalate_p1                   skip create_ticket
  (page oncall)                  link to existing incident
      │
      ▼
  create_ticket  →  send_notifications (email + Slack, parallel)
```

**Coherence rule:** If severity is P1 but confidence < 0.5, the system auto-degrades to P2 and flags `needs_human_review=True`. This prevents automated over-escalation on uncertain signals.

---

## Key Technical Differentiators

**1. Multi-model orchestration.** `claude-sonnet-4-6` acts as the reasoning orchestrator. `claude-haiku-4-5-20251001` handles log parsing and image analysis — tasks where extraction speed matters more than deep reasoning. Each model is assigned to the role it is best suited for.

**2. Conditional attachment tools.** `analyze_logs` and `analyze_images` are declared as tools with explicit trigger conditions in their descriptions. Claude reads the attachment manifest in the initial message and autonomously invokes them only when relevant. A text-only report runs 3 parallel tools; a report with logs and a dashboard screenshot runs 5.

**3. RAG over your actual codebase.** The indexer clones the production codebase and embeds it into ChromaDB at startup. Code analysis is not LLM priors — it is a semantic search against the real repository. The root-cause hypothesis cites actual file paths and functions.

**4. ReAct over fixed graph.** The prior LangGraph `StateGraph` implementation required hardcoded conditional edges for every routing scenario. With ReAct, adding a new investigation capability requires one tool handler and one schema entry — Claude routes to it automatically based on its description.

**5. P1 coherence rule.** A guardrail that makes automated escalation structurally conservative: the system cannot auto-escalate to P1 unless it is also confident. This prevents alert fatigue from automated false positives.

---

## What the Output Looks Like

A completed triage produces:

- **Severity:** P1–P4 with a calibrated confidence score (0.0–1.0)
- **Root cause hypothesis:** grounded in specific code files and functions from your actual codebase
- **Runbook:** structured remediation steps with exact shell/kubectl/SQL commands
- **Investigation steps:** ordered diagnostic actions for the on-call engineer
- **Jira ticket:** pre-filled with all of the above, priority-mapped (P1→Critical, P2→High, etc.), assigned to the correct team
- **Notifications:** severity-aware emails to team and reporter; Slack post with `@oncall` mention for P1

---

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/your-org/incident-cortex.git
cd incident-cortex
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY (required)

# 2. Start everything
docker compose up -d

# 3. Wait for codebase indexing (~5–10 min on first run)
docker compose logs indexer -f
# → "Indexing complete"

# 4. Open the UI
open http://localhost:3000
```

| Service | URL |
|---|---|
| Frontend UI | http://localhost:3000 |
| API + Swagger docs | http://localhost:8000/docs |
| MailHog (captured emails) | http://localhost:8025 |
| Jira Mock (browse tickets) | http://localhost:8081 |
| Slack Mock | http://localhost:8090 |
| Langfuse (LLM traces) | http://localhost:3001 |

---

## Architecture

**Orchestrator** (`backend/app/agents/orchestrator.py`): ReAct loop over the Anthropic Messages API. Dispatches tool calls, collects results with `asyncio.gather`, streams WebSocket events per tool completion. Max 15 iterations; 90s timeout per turn.

**Tool handlers** (`backend/app/agents/`): Each tool is a focused async function that reads from and writes to a shared state dict. Parallel tools write to disjoint state keys (`code_analysis`, `dedup_result`, `metrics_result`, `log_analysis`, `image_analysis`), making concurrent execution safe without locks.

**ChromaDB vector store**: Two collections — `ecommerce_codebase` (indexed at startup) for code RAG, and an incidents collection for deduplication. The `vector_store.py` wrapper abstracts the client; swapping to Pinecone or Weaviate requires changing one file.

**PostgreSQL event store** (`services/event_store.py`): Every tool call result is persisted. Enables WebSocket replay, pipeline audit, and the `/api/metrics` endpoint (p50/p95 triage time, dedup rate, severity distribution).

**Guardrails** (`backend/app/guardrails/`): Three-layer defense — `injection_detector.py` (regex pattern matching + length heuristic), `input_sanitizer.py` (MIME allowlist, path traversal prevention, 10 MB file cap, HTML stripping), `output_validator.py` (severity enum check, confidence range [0,1], hypothesis minimum length).

**Observability**: Langfuse (LLM call traces with token counts and latency per call), OpenTelemetry spans (FastAPI auto-instrumented), PostgreSQL event log (full pipeline audit trail), `/api/metrics` endpoint.

---

## Tech Stack

| Component | Technology |
|---|---|
| Orchestrator LLM | `claude-sonnet-4-6` (Anthropic) |
| Specialized extraction LLM | `claude-haiku-4-5-20251001` (Anthropic) |
| Backend | FastAPI, Python 3.11, Pydantic |
| Orchestration pattern | ReAct tool-calling (Anthropic Messages API) |
| Vector store | ChromaDB |
| Embeddings | Sentence Transformers (default) or OpenAI ada-002 |
| Frontend | React 18, JSX |
| Event persistence | PostgreSQL |
| LLM tracing | Langfuse |
| Distributed tracing | OpenTelemetry |
| Email (demo) | MailHog (SMTP) |
| Jira (demo) | SQLite-backed mock (port 8081) |
| Slack (demo) | SQLite-backed mock (port 8090) |
| Containerization | Docker Compose (single-node, zero external dependencies) |
| Testing | pytest |

---

## Project Structure

```
incident-cortex/
├── backend/
│   └── app/
│       ├── agents/
│       │   ├── orchestrator.py      # ReAct loop + all 10 tool handlers
│       │   ├── intake.py            # parse_incident handler
│       │   ├── code_analysis.py     # search_codebase handler
│       │   ├── deduplication.py     # check_duplicates handler
│       │   ├── triage_synth.py      # synthesize_triage handler
│       │   ├── ticket_agent.py      # create_ticket handler
│       │   └── notification.py      # send_notifications handler
│       ├── guardrails/
│       │   ├── injection_detector.py
│       │   ├── input_sanitizer.py
│       │   └── output_validator.py
│       ├── observability/
│       │   ├── langfuse_client.py
│       │   └── tracing.py
│       ├── services/
│       │   ├── vector_store.py      # ChromaDB abstraction layer
│       │   └── event_store.py       # PostgreSQL event log
│       └── api/
│           ├── routes.py            # REST endpoints + rate limiting
│           └── websocket.py         # Real-time pipeline updates
├── frontend/src/
│   ├── IncidentForm.jsx
│   ├── IncidentList.jsx
│   ├── TriageView.jsx
│   └── App.jsx
├── indexer/
│   └── index_codebase.py            # One-shot codebase embedder
├── mock-services/                   # Jira + Slack SQLite mocks
├── docker-compose.yml
├── AGENTS_USE.md                    # Full agent documentation (hackathon submission)
├── AGENTS.md                        # Agent registry (machine-readable manifest)
├── SCALING.md                       # Scaling analysis and production path
├── QUICKGUIDE.md                    # Operations reference
└── .env.example
```

---

## Running Tests

```bash
# All tests (inside Docker)
docker compose exec backend pytest -v

# Single agent
docker compose exec backend pytest tests/agents/test_intake.py -v

# With coverage
docker compose exec backend pytest --cov=agents tests/
```

---

## License

MIT. See LICENSE for details.
