# Quick Start & Operations Guide

A one-page reference for running and troubleshooting Incident Cortex.

---

## Prerequisites

- **Docker & Docker Compose:** v20.10+
- **API Keys:**
  - `ANTHROPIC_API_KEY` (required) — Claude 3.5 Sonnet access
  - `OPENAI_API_KEY` (optional) — For OpenAI embeddings; defaults to Sentence Transformers if omitted
  - `JIRA_URL`, `JIRA_USER`, `JIRA_TOKEN` (optional) — For real Jira integration; mocked by default
  - `SLACK_BOT_TOKEN` (optional) — For real Slack integration; mocked by default

---

## Setup

```bash
# 1. Clone repo
git clone https://github.com/your-org/incident-cortex.git
cd incident-cortex

# 2. Copy environment template
cp .env.example .env

# 3. Edit .env with your API keys
# vim .env

# 4. Bring up all services
docker compose up -d

# 5. Monitor indexing progress
docker compose logs indexer -f
# Wait for: "Indexing complete: 1,234 files indexed"

# 6. Verify all services are healthy
docker compose ps
# All services should show "Up"

# 7. Access the UI
open http://localhost:3000
```

---

## Common Operations

### Submit an Incident via curl

```bash
curl -X POST http://localhost:8000/api/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "reporter": "alice@company.com",
    "title": "Login endpoint returning 500s",
    "description": "Users unable to log in. Started ~14:30 UTC. Affects ~500 users.",
    "source": "slack"
  }'

# Response:
# {
#   "incident_id": "INCIDENT-20260409-001",
#   "status": "processing",
#   "message": "Incident submitted. Triage in progress..."
# }
```

### Monitor Incident Status

```bash
curl http://localhost:8000/api/incidents/INCIDENT-20260409-001

# Response:
# {
#   "incident_id": "INCIDENT-20260409-001",
#   "status": "completed",
#   "severity": "P2",
#   "confidence": 0.88,
#   "triage_document": { ... }
# }
```

### View WebSocket Live Updates

Open browser DevTools and run:
```javascript
ws = new WebSocket('ws://localhost:8000/ws/incidents/INCIDENT-20260409-001');
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

### Run Tests

```bash
docker compose exec backend pytest -v

# Run specific test file:
docker compose exec backend pytest tests/agents/test_intake.py -v

# Run with coverage:
docker compose exec backend pytest --cov=agents tests/
```

### Reset and Re-Index Codebase

```bash
# Stop containers and remove volumes
docker compose down -v

# Start fresh
docker compose up -d

# Monitor indexing
docker compose logs indexer -f
```

### View Mock Jira

Open http://localhost:8080
Default credentials: `admin` / `password`

### View Mock Slack

Open http://localhost:8090
Simulates Slack API for testing notifications.

### Check MailHog (Email Testing)

Open http://localhost:8025
Captures all outgoing emails from the Notification Agent.

---

## Troubleshooting

### Indexer Fails to Start

**Symptom:** `docker compose logs indexer` shows errors.

**Solutions:**
1. Check disk space: `df -h` — ChromaDB needs ~1 GB
2. Verify codebase path exists: `ls -la ./reaction-commerce/` (if using default demo codebase)
3. Rebuild indexer image: `docker compose build --no-cache indexer`
4. Check for port conflicts: `lsof -i :6000` (ChromaDB default port)

### LLM Timeout

**Symptom:** "Timeout waiting for Claude response" in logs.

**Solutions:**
1. Verify `ANTHROPIC_API_KEY` is valid: `curl -H "Authorization: Bearer $ANTHROPIC_API_KEY" https://api.anthropic.com/health`
2. Check network latency: `ping api.anthropic.com`
3. Increase timeout in `.env`: `LLM_TIMEOUT_SECONDS=60` (default: 30)
4. Check if rate-limited: look for "429" errors in logs

### ChromaDB Connection Refused

**Symptom:** "Connection refused: 127.0.0.1:6000" in backend logs.

**Solutions:**
1. Check ChromaDB is running: `docker compose ps | grep chroma`
2. Restart ChromaDB: `docker compose restart chroma`
3. Check logs: `docker compose logs chroma`
4. Verify port mapping: `docker compose config | grep -A 5 'chroma:'`

### Backend API Won't Start

**Symptom:** `docker compose logs backend` shows import or config errors.

**Solutions:**
1. Rebuild image: `docker compose build backend`
2. Check Python version: `python --version` (need 3.11+)
3. Check for missing env vars: `grep -r "os.getenv" backend/ | grep "required"`
4. Inspect startup logs: `docker compose logs backend --tail 50`

### Frontend Blank Screen

**Symptom:** http://localhost:3000 loads but shows nothing.

**Solutions:**
1. Check frontend logs: `docker compose logs frontend`
2. Open browser DevTools → Console tab for JavaScript errors
3. Verify API is reachable: `curl http://localhost:8000/health`
4. Clear browser cache: Cmd+Shift+R (Mac) or Ctrl+Shift+R (Windows)

---

## Environment Variables Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | (required) | Claude API key |
| `OPENAI_API_KEY` | (optional) | OpenAI embeddings; omit for Sentence Transformers |
| `CHROMA_HOST` | `chroma` | ChromaDB hostname (Docker) |
| `CHROMA_PORT` | `6000` | ChromaDB port |
| `JIRA_MOCK_MODE` | `true` | Use mock Jira; set `false` for real Jira |
| `JIRA_URL` | (optional) | Real Jira instance URL |
| `JIRA_USER` | (optional) | Jira username |
| `JIRA_TOKEN` | (optional) | Jira API token |
| `SLACK_MOCK_MODE` | `true` | Use mock Slack; set `false` for real Slack |
| `SLACK_BOT_TOKEN` | (optional) | Slack bot token |
| `DEDUP_SIMILARITY_THRESHOLD` | `0.75` | Duplicate detection sensitivity (0.0–1.0) |
| `LLM_TIMEOUT_SECONDS` | `30` | Max time to wait for Claude response |
| `LOG_LEVEL` | `INFO` | Logging verbosity: DEBUG, INFO, WARN, ERROR |
| `CODEBASE_PATH` | `./reaction-commerce` | Path to codebase for indexing |

---

## Healthy System Check

```bash
# Run all checks
curl http://localhost:8000/health

# Expected response:
# {
#   "status": "healthy",
#   "components": {
#     "backend": "ok",
#     "chroma": "ok",
#     "frontend": "ok"
#   }
# }
```

---

## Next Steps

- Read `AGENTS_USE.md` for deep dive into each agent
- Read `README.md` for architecture overview
- Try the 3-minute demo in `docs/DEMO.md`
- Customize dedup threshold for your incident volume
- Integrate with your real Jira, Slack, and email services

---

## Support

- Check logs: `docker compose logs [service]`
- Run tests: `docker compose exec backend pytest -v`
- Check health: `curl http://localhost:8000/health`
- Reset state: `docker compose down -v && docker compose up -d`
