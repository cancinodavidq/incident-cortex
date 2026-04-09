# Incident Cortex

> SRE Incident Intake & Triage Agent — AgentX Hackathon 2026

**One-line pitch:** "Incident Cortex reads your codebase to triage incidents. The output isn't 'P2 - backend issue.' It's the document a senior SRE would spend 30 minutes producing — in seconds."

## How it works

Incident Cortex processes raw incident reports through a 6-agent pipeline to produce a comprehensive triage document that includes severity assessment, confidence scores, root cause hypotheses, affected services, and automated ticket/notification actions.

```
┌─────────────────┐
│  INTAKE AGENT   │  Parse incident report, extract structured data
└────────┬────────┘
         │
    ┌────┴─────────────────────────────┐  (parallel)
    │                                  │
┌───▼──────────────────┐  ┌────────────▼──────────┐
│  CODE ANALYSIS AGENT │  │     DEDUP AGENT       │
│  ChromaDB RAG search │  │  Semantic similarity  │
└───────────┬──────────┘  └────────────┬──────────┘
            └──────────┬───────────────┘
                       │
         ┌─────────────▼─────────────────┐
         │    TRIAGE SYNTHESIZER AGENT   │  Severity + runbook generation
         └──────────┬────────────────────┘
                    │
         ┌──────────┼─────────────────────────┐
         │          │                         │
   (P1 only)    (P2-P4)               (duplicate)
┌────▼──────┐  ┌────▼──┐              ┌───────▼──────┐
│ ESCALATE  │  │Ticket │              │  Link Exist. │
│ @oncall   │  │Agent  │              │  (skip ticket│
└────┬──────┘  └───┬───┘              └──────┬───────┘
     └─────────────┴──────────────────────────┘
                                       │
                              ┌────────▼────────┐
                              │  NOTIFY AGENT   │  Email + Slack
                              └─────────────────┘
```

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/your-org/incident-cortex.git
cd incident-cortex
cp .env.example .env
# Edit .env: add ANTHROPIC_API_KEY (required), optionally OPENAI_API_KEY for embeddings

# 2. Launch everything
docker compose up -d

# 3. Wait for indexing to complete (~5-10 min)
docker compose logs indexer -f

# 4. Open the UI
open http://localhost:3000

# Services:
# Frontend:    http://localhost:3000
# API docs:    http://localhost:8000/docs
# MailHog:     http://localhost:8025
# Jira Mock:   http://localhost:8081   ← browse tickets here
# Slack Mock:  http://localhost:8090
# Langfuse:    http://localhost:3001
```

## Architecture

**Frontend (React 18):** Web UI for submitting incidents, viewing live triage progress via WebSocket, and monitoring pipeline metrics. No TypeScript — pure JSX with a CSS custom-properties design system.

**Backend API (FastAPI + LangGraph):** REST & WebSocket server orchestrating the 7-node LangGraph StateGraph. Each agent streams progress events over WebSocket in real-time.

**Agent Pipeline (7 nodes):**
- **Intake** — Parse raw text into structured `ParsedIncident`
- **Code Analysis** (parallel) — ChromaDB RAG search of indexed e-commerce codebase
- **Dedup** (parallel) — Semantic similarity against past incidents; auto-links duplicates
- **Triage Synthesizer** — P1-P4 severity + confidence score + root cause + **runbook generation**
- **Escalate** (P1 only) — Fast-path: page oncall, broadcast urgent WebSocket event
- **Ticket** — Create Jira issue with priority mapping
- **Notify** — Email (team + reporter) + Slack, with P1 urgency handling

**ChromaDB Vector Store:** Reaction Commerce codebase indexed as embeddings for RAG-based code analysis.

**Mock External Services:** Jira (port 8081), Slack (port 8090), MailHog (port 8025) — SQLite-persisted, no external API keys needed.

## Demo Script

A 3-minute demo script is available in the `docs/DEMO.md` file. It walks through:
1. Submitting an incident via the web UI
2. Watching the agent pipeline execute in real-time
3. Viewing the final triage document with severity, confidence, and action items

## Stack

| Component | Technology |
|-----------|-----------|
| **Frontend** | React 18, TypeScript, TailwindCSS |
| **Backend** | FastAPI, Python 3.11+, Pydantic |
| **Agent Framework** | LangGraph, LangChain |
| **LLM** | Claude 3.5 Sonnet (Anthropic) |
| **Vector DB** | ChromaDB (Python) |
| **Embeddings** | OpenAI embeddings or Sentence Transformers |
| **External Services** | Jira, Slack, SMTP |
| **Containerization** | Docker, Docker Compose |
| **Testing** | pytest, Playwright (E2E) |
| **Monitoring** | Logging, structured event tracing |

## Project Structure

```
incident-cortex/
├── backend/                    # FastAPI server & LangGraph agents
│   ├── agents/                 # Individual agent implementations
│   │   ├── intake.py
│   │   ├── code_analysis.py
│   │   ├── dedup.py
│   │   ├── synthesizer.py
│   │   ├── ticket.py
│   │   └── notification.py
│   ├── services/               # External integrations (Jira, Slack, email)
│   ├── models/                 # Pydantic schemas for state & requests
│   ├── chroma_client.py        # Vector DB setup & retrieval
│   ├── main.py                 # FastAPI app entrypoint
│   └── requirements.txt
├── frontend/                   # React UI
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── App.tsx
│   └── package.json
├── docker-compose.yml          # Orchestration: backend, frontend, services
├── .env.example                # Template for environment variables
├── .gitignore
├── README.md
└── docs/
    ├── AGENTS_USE.md           # Detailed agent documentation
    ├── QUICKGUIDE.md           # Operational reference
    └── DEMO.md                 # 3-minute demo walkthrough
```

## Contributing

See `QUICKGUIDE.md` for setup, testing, and operational instructions.

## License

MIT. See LICENSE for details.
