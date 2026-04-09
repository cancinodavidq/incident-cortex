# AGENTS.md — Incident Cortex Agent Registry

This file is the machine-readable manifest for the Incident Cortex 6-agent LangGraph pipeline.
It defines each agent's capabilities, inputs, outputs, routing behavior, and operational constraints.

## Architecture Pattern: ReAct Tool-Calling

Incident Cortex uses the **ReAct (Reasoning + Acting)** pattern via Claude's native tool use API.
Instead of a fixed LangGraph StateGraph, Claude autonomously decides which tools to call and in what order.

```
User incident text
       │
       ▼
Claude (claude-sonnet-4-6) ←──── tool_result blocks
       │
       ▼ (tool_use blocks — may call multiple tools per turn)
   Tool Dispatch
   ┌──────────────────────────────────────────────────────┐
   │  parse_incident  │  search_codebase  │ check_duplicates │
   │  synthesize_triage  │  escalate_p1  │  create_ticket   │
   │                  send_notifications                  │
   └──────────────────────────────────────────────────────┘
       │
       ▼
 Loop until stop_reason = "end_turn" (max 15 iterations)
```

**Key properties:**
- Claude calls multiple tools simultaneously in a single turn (e.g., `search_codebase` + `check_duplicates`)
- Tool handlers mutate a shared `state` dict (replaces IncidentState TypedDict)
- No hardcoded routing — Claude reasons about what to do next based on tool results
- Max 15 iterations prevents infinite loops
- Each tool call broadcasts WS events for real-time UI updates

All agent state flows through a mutable `dict` passed to each tool handler.

---

## Agent Definitions

### 1. intake
- **File**: `backend/app/agents/intake.py`
- **Role**: Parse raw incident text into structured `ParsedIncident`
- **Model**: Claude (claude-sonnet-4-5 via `LLMClient`)
- **Input fields**: `raw_text`, `attachments`, `reporter_email`
- **Output fields**: `parsed_incident` (title, description, affected_service, error_type, symptoms, information_sufficient)
- **Routing**:
  - `information_sufficient=True` → Send parallel: `[code_analysis, dedup]`
  - `information_sufficient=False` → `request_clarity` (terminal)
- **Retry**: 0 (fail fast, conservative fallback)
- **Timeout**: 30s
- **Failure mode**: Returns `ParsedIncident` with `information_sufficient=False`

---

### 2. code_analysis
- **File**: `backend/app/agents/code_analysis.py`
- **Role**: Search codebase via ChromaDB RAG to identify relevant files and functions
- **Model**: Claude + ChromaDB vector search (collection: `ecommerce_codebase`)
- **Input fields**: `parsed_incident` (affected_service, error_type, symptoms)
- **Output fields**: `code_analysis` (relevant_files, suspected_functions, analysis_summary, degraded)
- **Runs**: In parallel with `dedup`
- **Degraded mode**: If ChromaDB unavailable, returns `degraded=True` with empty files (pipeline continues)
- **Timeout**: 45s

---

### 3. dedup
- **File**: `backend/app/agents/deduplication.py`
- **Role**: Semantic deduplication via incident embeddings
- **Model**: Sentence Transformers / OpenAI embeddings + ChromaDB
- **Input fields**: `parsed_incident`, `raw_text`
- **Output fields**: `dedup_result` (is_duplicate, highest_similarity, recommendation, linked_incident_id, similar_incidents)
- **Runs**: In parallel with `code_analysis`
- **Thresholds**:
  - `similarity ≥ 0.95` → `recommendation = "merge"` (confirmed duplicate)
  - `0.85 ≤ similarity < 0.95` → `recommendation = "link_existing"` (routes away from ticket)
  - `0.75 ≤ similarity < 0.85` → `recommendation = "link_existing_soft"` (suggestion only)
  - `similarity < 0.75` → `recommendation = "create_new"`
- **Timeout**: 20s

---

### 4. triage_synth
- **File**: `backend/app/agents/triage_synth.py`
- **Role**: Synthesize severity verdict, root cause hypothesis, investigation steps, and runbook
- **Model**: Claude (primary reasoning agent)
- **Input fields**: `parsed_incident`, `code_analysis`, `dedup_result`
- **Output fields**: `triage_verdict` (severity P1-P4, confidence, root_cause_hypothesis, affected_components, investigation_steps, runbook, suggested_assignee_team, needs_human_review)
- **Coherence rules**:
  - P1 + confidence < 0.5 → auto-degrade to P2 + set `needs_human_review=True`
  - confidence < 0.6 → always set `needs_human_review=True`
- **Routing**:
  - `severity = P1` → `escalate` node (fast path)
  - `severity ∈ {P2,P3,P4}` → `ticket`
  - `dedup.is_duplicate AND similarity ≥ 0.85` → `notify` (skip ticket)
- **Skip condition**: If dedup confirms duplicate (similarity ≥ 0.85), returns early with `triage_verdict=None`
- **Timeout**: 60s

---

### 5. escalate (conditional — P1 only)
- **File**: `backend/app/agents/orchestrator.py` (inline node)
- **Role**: P1 fast-path escalation: page oncall, flag state, emit urgent WebSocket event
- **Triggers**: `triage_verdict.severity == "P1"`
- **Input fields**: `triage_verdict`, `parsed_incident`
- **Output fields**: `escalation_triggered=True`
- **Side effects**: Broadcasts `agent_completed/escalate` with oncall message over WebSocket
- **Routes to**: `ticket` (always, after escalation marker is set)
- **Timeout**: 5s (no LLM call)

---

### 6. ticket
- **File**: `backend/app/agents/ticket_agent.py`
- **Role**: Create Jira ticket via mock API
- **Input fields**: `triage_verdict`, `parsed_incident`, `code_analysis`
- **Output fields**: `ticket_id`, `ticket_url`
- **Jira priority mapping**: P1→Critical, P2→High, P3→Medium, P4→Low
- **Retry**: 1 (total 2 attempts)
- **Failure mode**: Returns `ticket_id = "MANUAL-REQUIRED"`
- **Timeout**: 10s per attempt

---

### 7. notify
- **File**: `backend/app/agents/notification.py`
- **Role**: Send email (team + reporter) and Slack notifications in parallel
- **Input fields**: `triage_verdict`, `parsed_incident`, `ticket_id`, `reporter_email`, `dedup_result`, `escalation_triggered`
- **Output fields**: `notifications_sent` (list of: "team_email", "reporter_email", "slack")
- **Parallelism**: All 3 notifications sent concurrently via `asyncio.gather`
- **P1 behavior**: Urgent subject line + `@oncall` Slack mention when `escalation_triggered=True`
- **Duplicate behavior**: Reporter gets "linked to existing" email instead of triage summary
- **Timeout**: 10s per notification

---

## Sub-Agent Patterns

### Parallel Fan-out (code_analysis + dedup)
LangGraph `Send()` API dispatches both agents simultaneously after intake.
`join_analysis` node collects results before triage_synth runs.

### Conditional Fast-Path (P1 Escalation)
`_route_after_triage()` returns `"escalate"` for P1 severity.
The escalate node sets `escalation_triggered=True` in state, then routes to `ticket`.
This gives notification_agent a flag to send urgent alerts.

### Early Exit (Duplicate Routing)
If `dedup.highest_similarity ≥ 0.85`, `_route_after_triage()` returns `"link_existing"`.
Pipeline skips ticket creation and goes directly to notify.
Triage synthesizer also exits early if duplicate is confirmed.

---

## Configuration

All agent thresholds and settings in `backend/app/config.py`:

| Setting | Default | Agent |
|---------|---------|-------|
| `DEDUP_SUGGESTION_THRESHOLD` | 0.75 | dedup |
| `DEDUP_DUPLICATE_THRESHOLD` | 0.85 | dedup, triage_synth |
| `ANTHROPIC_API_KEY` | required | all LLM agents |
| `JIRA_MOCK_URL` | `http://jira-mock:8080` | ticket |
| `SLACK_MOCK_URL` | `http://slack-mock:8090` | notify |
| `MAILHOG_SMTP_HOST` | `mailhog` | notify |
| `CHROMA_HOST` / `CHROMA_PORT` | `chromadb` / `8001` | code_analysis, dedup |

---

## Observability

- LLM calls traced via Langfuse (configure `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`)
- Pipeline events persisted to PostgreSQL via `EventStore`
- WebSocket broadcasting at `ws://backend:8000/ws/{incident_id}` for live UI updates
- Metrics endpoint: `GET /api/metrics` → severity distribution, triage times, dedup rate
- OpenTelemetry spans in `backend/app/observability/tracing.py`
