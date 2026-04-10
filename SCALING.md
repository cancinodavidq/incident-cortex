# SCALING.md — Incident Cortex

This document explains how Incident Cortex is designed to scale, the assumptions made for the current deployment, and the technical decisions that govern growth paths.

---

## Current Deployment Assumptions

The `docker-compose.yml` configuration is a **single-node, all-in-one deployment** designed for demo and evaluation purposes. Every service runs as a container on the same host. This is intentional: the hackathon constraint is reproducibility, not production readiness.

Key assumptions baked into this baseline:

- One backend process handles all concurrent incident submissions.
- ChromaDB runs in-process on a single container with a local volume.
- PostgreSQL is a single instance with no replication.
- WebSocket connections are managed in-process (no external broker).
- The indexer runs once at startup and is not re-triggered.
- Rate limiting is a static cap (`RATE_LIMIT_PER_MINUTE=10`) enforced in the FastAPI middleware, not at the infrastructure level.

This works for low-concurrency usage (demo, small team triage) but breaks under sustained load or multi-node deployment.

---

## Where Bottlenecks Appear First

### 1. LLM call latency

Each incident triggers 3–5 sequential or parallel LLM calls (intake, code analysis, triage synthesis, and optionally escalate). At ~2–4 seconds per call, end-to-end latency is ~10–15 seconds. Under concurrent load, requests queue behind each other.

**Design decision:** Code analysis and dedup already run in parallel via `LangGraph Send()`. This was a deliberate choice to cut the longest path on the critical chain. Further parallelism would require LLM call batching, which the Anthropic SDK supports but is not wired in here.

### 2. ChromaDB

ChromaDB is embedded and single-threaded under the default `chromadb/chroma` Docker image. All RAG queries from code analysis serialize through one process.

**Design decision:** ChromaDB was chosen for zero-config startup during the hackathon. It is a drop-in replacement target for Pinecone, Weaviate, or Qdrant if horizontal read throughput becomes the constraint. The `vector_store.py` service wrapper abstracts the client so the backend never calls ChromaDB directly — swapping the implementation requires changing one file.

### 3. WebSocket state

FastAPI manages WebSocket connections in-process using an in-memory connection registry. If the backend scales to multiple replicas, a client connected to replica A will not receive events emitted by a pipeline running on replica B.

**Design decision:** This is the primary architectural debt for multi-node deployment. The fix is to route WebSocket events through a Redis pub/sub channel. The `event_store.py` layer already writes all pipeline events to PostgreSQL, so a fallback polling mechanism is available as a bridge until Redis is added.

### 4. PostgreSQL

The event store, incident history, and Langfuse observability all write to a single PostgreSQL instance. Under high write volume (many concurrent incidents), this becomes a contention point.

**Design decision:** Read replicas are the first lever. Langfuse can be pointed at a separate database or replaced with a managed observability service without touching the core pipeline.

---

## Horizontal Scaling Path

The backend is stateless between requests (all state lives in PostgreSQL and ChromaDB). Horizontal scaling follows this sequence:

1. **Add a load balancer** in front of multiple `backend` replicas. Sticky sessions are required only for WebSocket upgrades — REST endpoints are fully stateless.
2. **Add Redis pub/sub** to broadcast pipeline events across replicas. WebSocket handlers subscribe to a channel keyed by `incident_id` rather than holding an in-process registry.
3. **Move ChromaDB to a managed vector store** (Pinecone, Weaviate) or run ChromaDB in distributed mode once read throughput saturates a single node.
4. **Move PostgreSQL to a managed service** (RDS, CloudSQL) with read replicas. Connection pooling via PgBouncer sits between the backend and the database.
5. **Add a task queue** (Celery + Redis, or Temporal) in front of the LangGraph pipeline so that incident submissions are accepted immediately and processed asynchronously, decoupling HTTP response time from pipeline latency.

---

## LangGraph Pipeline Scalability

LangGraph `StateGraph` instances are created per-request and carry no cross-request state. Each node receives a copy of `IncidentState` and returns a partial update. This design is inherently parallelizable:

- Multiple pipelines run concurrently today, bounded only by the event loop and LLM concurrency limits.
- Nodes can be extracted into separate workers (e.g., Celery tasks) if pipeline steps need independent scaling — the state dict is serializable and can transit a message queue.
- The dedup agent uses ChromaDB similarity search with a configurable threshold (`DEDUP_SIMILARITY_THRESHOLD`). Raising the threshold reduces false positives but increases ticket volume; this is a product decision, not a scaling decision.

---

## Indexer

The indexer is a one-shot container that clones the e-commerce repository and indexes it into ChromaDB. It does not run again unless volumes are deleted.

**Scaling assumption:** The indexed codebase does not change frequently. For a production deployment, the indexer would become a scheduled job (daily or on push to the target repo), and new embeddings would be upserted rather than triggering a full re-index.

---

## Rate Limiting

The current `RATE_LIMIT_PER_MINUTE=10` cap is per-process, enforced in FastAPI middleware. Under multiple replicas, each replica enforces its own cap, so the effective system limit multiplies with replica count.

For true rate limiting across replicas, the counter must move to Redis or a gateway layer (e.g., Kong, Nginx rate limit module, AWS API Gateway).

---

## Mock Services

Jira Mock, Slack Mock, and MailHog are SQLite-backed containers included for demo isolation. They are not intended to scale. In production, these are replaced by direct API integrations with Jira, Slack, and an SMTP relay (SendGrid, SES). The backend calls these through a thin service interface (`services/jira_client.py`, `services/slack_client.py`) — no pipeline agent holds a direct dependency on the mock.

---

## Summary of Technical Decisions

| Decision | Rationale | Production Replacement |
|---|---|---|
| Single-node Docker Compose | Zero-config demo reproducibility | Kubernetes / ECS task definitions |
| ChromaDB in-container | No external service required at startup | Pinecone, Weaviate, or distributed ChromaDB |
| In-process WebSocket registry | Simplicity for single-node | Redis pub/sub |
| Async ReAct loop (asyncio) | Parallel tool dispatch without a task queue | Celery or Temporal for true async pipeline |
| Static rate limit per process | Sufficient for demo volume | Redis-backed distributed counter |
| SQLite mock services | Offline demo, no external API keys | Jira API, Slack API, SMTP relay |
| Langfuse for LLM tracing | Self-hosted, no external dependency | Langfuse Cloud or Datadog LLM observability |
| Multi-model (Sonnet + Haiku), no OpenRouter | OpenRouter not viable for orchestrator: the ReAct loop depends on Anthropic's native `tool_use`/`tool_result` message format, which other providers implement differently. Haiku already achieves the cost reduction OpenRouter would offer for extraction-only calls (log analysis, image analysis) — ~80% cheaper than Sonnet with no measurable quality loss for those tasks. OpenRouter remains listed in config (`OPENROUTER_MODEL`) as a future path for non-tool-use LLM calls only. | Direct provider integrations (OpenAI, Gemini) behind an abstraction layer that translates tool schemas per provider |
