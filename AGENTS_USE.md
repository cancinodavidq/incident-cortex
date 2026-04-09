# Agent Pipeline: Detailed Reference

This document explains each of the 6 agents in the Incident Cortex pipeline: what they do, their inputs and outputs, and how they handle failures.

---

## 1. INTAKE AGENT

**Purpose:** Parse raw incident reports into structured data.

**Inputs:**
- Unstructured incident report (text, Slack message, email, or form submission)
- Metadata: reporter name, timestamp, channel/source

**Process:**
The Intake Agent reads the raw report and uses Claude to extract:
- **Service affected** (inferred from context clues: service names, error logs, domain)
- **Symptom description** (what the user observed)
- **Error messages** (if any)
- **User impact** (how many users affected, business impact estimate)
- **Timeline** (when did it start, how long has it been happening)
- **Affected components** (microservices, databases, external APIs)

**Outputs:**
```python
{
    "report_id": "INCIDENT-20260409-001",
    "service_affected": ["api-gateway", "user-service"],
    "symptom": "Intermittent 500 errors on login endpoint",
    "error_messages": ["Exception in UserAuthenticator: connection timeout"],
    "user_impact": "~500 users unable to log in",
    "timeline_start": "2026-04-09T14:32:00Z",
    "duration_minutes": 8,
    "severity_guess": "P2",
    "keywords": ["auth", "timeout", "database"]
}
```

**Failure Modes:**
- **Vague reports:** If the report lacks specifics, the agent marks fields as `null` and flags for Code Analysis Agent to investigate.
- **Hallucinated services:** If the report mentions a service that doesn't exist in the codebase, the agent flags it as "unverified" so Code Analysis can validate.
- **Incomplete extraction:** Missing fields are filled with reasonable defaults or marked as uncertain.

---

## 2. CODE ANALYSIS AGENT

**Purpose:** Search the codebase to verify extracted data and build context for triage.

**Inputs:**
- Structured incident data from Intake Agent
- ChromaDB vector store (codebase embeddings)
- File metadata: paths, language, last modified date

**Process:**

The Code Analysis Agent performs **Retrieval-Augmented Generation (RAG)**:

1. **Query ChromaDB:** Use incident keywords (service names, error messages) to retrieve relevant code files:
   ```
   Query: "api-gateway login timeout"
   → [api-gateway/auth.py, api-gateway/config.py, db_connection.py]
   ```

2. **Verify affected services:** Cross-reference mentioned services against actual files in the codebase. If a file is found, confidence increases; if not found, flag as "service does not exist."

3. **Extract context:** For each retrieved file, extract:
   - Recent commits / last modified
   - Error handling code
   - Configuration (timeouts, retry logic)
   - Dependencies and integrations

4. **Build hypothesis:** Synthesize code context with incident data to form a root-cause hypothesis:
   - "Login timeout → database connection pool exhaustion (seen in db_connection.py line 145)"
   - "Configuration shows 30s timeout but query typically takes 5s; under load, queue time exceeds limit"

**Outputs:**
```python
{
    "verified_services": ["api-gateway", "user-service"],
    "unverified_services": [],
    "relevant_files": [
        {
            "path": "backend/services/user-service/auth.py",
            "context": "Password validation loop: 5 iterations per login...",
            "recent_changes": "Modified 2026-04-08 - added async retry logic",
            "confidence": 0.95
        },
        {
            "path": "backend/db_connection.py",
            "context": "Pool size: 20, timeout: 30s, idle timeout: 300s",
            "confidence": 0.85
        }
    ],
    "hypothesis": "Database connection pool exhaustion under high concurrent login load",
    "evidence_strength": 0.88
}
```

**Why File Verification Matters:**
- **Prevents false triaging:** If a service doesn't exist, the Synthesizer knows to deprioritize that thread.
- **Boosts confidence:** Verified files increase confidence in the hypothesis.
- **Guides investigation:** The team knows exactly which files to check first.

**Failure Modes:**
- **ChromaDB connection refused:** Agent retries with exponential backoff. If all retries fail, fallback to keyword matching against cached file index.
- **Embedding timeout:** If embedding generation is slow, agent times out after 30s and uses the Intake Agent's structured data only (no RAG context).
- **No relevant files found:** Hypothesis confidence drops; Synthesizer will assign higher uncertainty scores.

---

## 3. DEDUP AGENT

**Purpose:** Check for duplicate incidents and merge if necessary.

**Inputs:**
- Current incident (from Intake + Code Analysis)
- Historical incident database (ChromaDB incidents collection)

**Process:**

The Dedup Agent compares the current incident against recent incidents using **cosine similarity** on embeddings:

1. **Embed the current incident:** Summarize into a single semantic vector.
2. **Search historical incidents:** Retrieve top 5 most similar incidents from the database.
3. **Compute similarity threshold:** Use a configurable threshold (default: 0.75).
   - **Similarity > 0.85:** Likely duplicate → flag for merge
   - **0.75 < Similarity < 0.85:** Possible duplicate → return with confidence score
   - **Similarity < 0.75:** Distinct incident → proceed

4. **Merge decision:** If similarity > 0.85, merge incidents:
   - Link the current report to the original incident ID
   - Update timeline: extend end time or note recurrence
   - Increment occurrence counter
   - Flag: "This is occurrence #3 of the same root cause"

**Outputs:**
```python
{
    "is_duplicate": True,
    "duplicate_of": "INCIDENT-20260409-001",
    "similarity": 0.92,
    "merge_action": "LINK_AND_EXTEND",
    "original_timeline": "2026-04-09T14:32:00Z - 2026-04-09T14:55:00Z",
    "new_timeline": "2026-04-09T14:32:00Z - 2026-04-09T15:30:00Z",
    "occurrence_count": 3
}
```

**How Similarity Thresholds Work:**
- Threshold is tunable via `DEDUP_SIMILARITY_THRESHOLD` env var.
- Higher threshold = fewer false positives but may miss related incidents.
- Lower threshold = catch more related incidents but increase false positive merges.
- Default (0.75) balances sensitivity and specificity.

**What Gets Stored:**
- Merged incidents retain their original ID but are linked in the database.
- Metadata includes merge history: when, why, and which incidents were combined.
- Statistics track: first occurrence, most recent, recurrence pattern.

**Failure Modes:**
- **No historical data:** On first run, database is empty; all incidents proceed without dedup.
- **Stale embeddings:** If historical incidents are weeks old, similarity may be unreliable. Agent flags age and suggests manual review.

---

## 4. TRIAGE SYNTHESIZER AGENT

**Purpose:** Combine signals from Intake, Code Analysis, and Dedup to assign severity, confidence, and action items.

**Inputs:**
- Intake Agent output (structured incident data)
- Code Analysis output (verified services, hypothesis, evidence strength)
- Dedup output (is_duplicate, merge status)

**Process:**

The Synthesizer uses a **multi-signal scoring model**:

1. **Severity Assignment (P1–P4):**
   ```
   Score = 0.4 * user_impact + 0.3 * service_criticality + 0.2 * evidence_strength + 0.1 * recurrence

   Score >= 0.85 → P1 (Critical)
   0.65 <= Score < 0.85 → P2 (High)
   0.40 <= Score < 0.65 → P3 (Medium)
   Score < 0.40 → P4 (Low)
   ```

   - **user_impact:** Fraction of affected users (inferred from Intake)
   - **service_criticality:** Is this service in the critical path? (from codebase analysis)
   - **evidence_strength:** How confident is the hypothesis? (from Code Analysis)
   - **recurrence:** Has this happened before? (from Dedup)

2. **Confidence Calibration:**
   ```
   Confidence = min(code_analysis_confidence, service_verification_rate, data_completeness)

   If (Severity > P2) and (Confidence < 0.60):
       Mark as "ESCALATE_TO_SRE_HUMAN"
   ```

   The Synthesizer enforces a **P1/Confidence coherence rule**: If an incident is P1 but confidence is low, it refuses to auto-escalate. Instead, it flags for human review with recommended next steps.

3. **Action Items:** Generate specific recommendations:
   - "Investigate user-service/auth.py line 145 for pool exhaustion"
   - "Check database replica lag with: `SELECT * FROM replication_status`"
   - "Consider rolling back commit abc123 (deployed 2026-04-08 22:15 UTC)"

**Outputs:**
```python
{
    "severity": "P2",
    "severity_score": 0.72,
    "confidence": 0.88,
    "confidence_level": "HIGH",
    "coherence_check": "PASS",
    "root_cause_hypothesis": "Database connection pool exhaustion under concurrent login load",
    "affected_services": ["user-service", "auth-service"],
    "action_items": [
        "Investigate user-service/auth.py line 145",
        "Check DB pool metrics: active connections, queued requests",
        "Consider rate-limiting login endpoint"
    ],
    "escalation": None,
    "recommended_owner": "Database SRE Team"
}
```

**Confidence Calibration Details:**

Confidence is NOT the same as severity. A P1 incident might have LOW confidence if:
- Code verification fails (services don't exist)
- Error messages are vague
- Timeline is unclear

The Synthesizer enforces: **"If P1 and Confidence < 0.60, require human approval before auto-escalating."**

This prevents over-automation and keeps humans in the loop for high-impact decisions.

**Failure Modes:**
- **Missing data from upstream agents:** If Code Analysis timed out, Synthesizer uses Intake data only and lowers confidence.
- **Contradictory signals:** If Dedup says "duplicate" but Code Analysis says "new root cause," Synthesizer flags the contradiction and asks for clarification.

---

## 5. TICKET AGENT

**Purpose:** Create tickets in Jira for human investigation and tracking.

**Inputs:**
- Synthesizer output (severity, confidence, action items)
- Jira credentials and project config

**Process:**

The Ticket Agent formats the Synthesizer's analysis into a Jira issue:

1. **Issue Template:**
   ```
   Title: [P2] Database Connection Pool Exhaustion - Login Service

   Description:
   Incident ID: INCIDENT-20260409-001
   Severity: P2 | Confidence: HIGH (0.88)

   Summary:
   Database connection pool exhaustion under concurrent login load.
   Approximately 500 users unable to log in (started 14:32 UTC, duration 8 min).

   Root Cause Hypothesis:
   User-service/auth.py performs 5 password validation iterations per login.
   Under peak load (e.g., 11:00 UTC EST), concurrent requests exceed DB pool size.

   Evidence:
   - File: backend/db_connection.py (Pool size: 20, timeout: 30s)
   - File: backend/services/user-service/auth.py (5x iteration loop)
   - Recurrence: 3rd occurrence in 2 days

   Action Items:
   [ ] Investigate pool metrics
   [ ] Review recent changes (commit abc123)
   [ ] Consider rate-limiting or connection pooling optimization

   Affected Services:
   - user-service
   - auth-service

   ===
   Generated by Incident Cortex (LangGraph SRE agent)
   ```

2. **Issue Assignment:** Based on Synthesizer's `recommended_owner`, assign to appropriate team/person.

3. **Labels:** Auto-tag with: `sre-triage`, `incident-cortex`, severity (`p1`, `p2`, etc.), service names.

4. **Link to related issues:** If Dedup found duplicates, link to original issue.

**Outputs:**
```python
{
    "ticket_id": "JIRA-12345",
    "url": "https://jira.internal/browse/JIRA-12345",
    "status": "created",
    "assigned_to": "database-sre-team",
    "created_at": "2026-04-09T15:35:00Z"
}
```

**Retry Logic:**
- **Transient failures (network):** Retry up to 3 times with exponential backoff (1s, 2s, 4s).
- **Auth failures:** Log error and alert ops team; do not auto-retry.
- **Jira validation errors:** Log issue details for manual creation; do not retry.

**Failure Modes:**
- **Jira unreachable:** Alert the backend team; incident remains open in Incident Cortex until ticket is created manually.
- **Auth token expired:** Gracefully fail with a clear error message for ops to refresh credentials.

---

## 6. NOTIFICATION AGENT

**Purpose:** Broadcast incident alerts through multiple channels in parallel.

**Inputs:**
- Synthesizer output (severity, action items, affected services)
- Notification config (channels, recipients, templates)

**Process:**

The Notification Agent sends alerts across **3 parallel channels**:

### Channel 1: Slack
- **Target:** #incidents Slack channel (broadcast) + on-call team's DM
- **Message format:**
  ```
  :alert: [P2] Database Connection Pool Exhaustion
  Service: user-service | Confidence: HIGH | 500 users affected

  Quick summary: Connection pool overload under login surge.

  Next steps:
  1. Check DB pool metrics
  2. Review recent changes

  Full details: [Link to Jira ticket]
  Incident ID: INCIDENT-20260409-001
  ```
- **On-call integration:** Look up on-call engineer from PagerDuty or config and send additional DM.

### Channel 2: Email
- **Target:** ops-team@company.com (distribution list) + incident reporter
- **Message format:**
  ```
  Subject: [INCIDENT] P2 - Database Connection Pool Exhaustion

  Incident ID: INCIDENT-20260409-001
  Severity: P2 | Confidence: HIGH

  [Full HTML report with graphs, timeline, affected users, action items]
  ```
- **Attachment:** PDF report (auto-generated) with triage summary.

### Channel 3: Dashboard Update
- **Target:** Internal incident dashboard (real-time UI)
- **Payload:**
  ```json
  {
    "incident_id": "INCIDENT-20260409-001",
    "severity": "P2",
    "status": "OPEN",
    "affected_users": 500,
    "affected_services": ["user-service"],
    "created_at": "2026-04-09T14:32:00Z",
    "triage_completed_at": "2026-04-09T15:35:00Z",
    "ticket_link": "https://jira.internal/browse/JIRA-12345"
  }
  ```

**Parallel Execution:**
All 3 channels are triggered in parallel; if one fails, the others still execute.

**Outputs:**
```python
{
    "slack_sent": True,
    "email_sent": True,
    "dashboard_updated": True,
    "timestamp": "2026-04-09T15:35:00Z",
    "status": "success"
}
```

**What Each Channel Receives:**
- **Slack:** Concise alert (fit in a message) + link to details.
- **Email:** Detailed report with full context, recommended actions, and executive summary.
- **Dashboard:** Structured JSON for real-time monitoring and historical trending.

---

## End-to-End Example

A user reports: *"API is returning 500s on login"*

1. **Intake Agent:** Extracts: service=api-gateway, symptom=500s, users affected=~500
2. **Code Analysis Agent:** Finds api-gateway/auth.py, user-service/db.py; hypothesis=pool exhaustion (confidence 0.88)
3. **Dedup Agent:** Matches 92% similarity to INCIDENT-20260409-001; merges (occurrence #3)
4. **Synthesizer:** Assigns P2 (score 0.72), confidence HIGH, action items
5. **Ticket Agent:** Creates JIRA-12345, assigns to database-sre-team
6. **Notification Agent:** Sends Slack alert, emails ops team, updates dashboard

**Total time: ~15 seconds.**

Senior SRE would spend 30 minutes doing this manually. Incident Cortex does it in seconds with structured output the team can act on immediately.
