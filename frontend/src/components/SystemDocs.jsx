import React, { useState } from "react";

// ── Shared primitives ─────────────────────────────────────────────────────────
function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 36 }}>
      <h2 style={{ fontSize: 13, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 16, paddingBottom: 8, borderBottom: "1px solid var(--border)" }}>
        {title}
      </h2>
      {children}
    </div>
  );
}

function Tag({ children, color = "#a5b4fc", bg = "rgba(165,180,252,.1)" }) {
  return (
    <span style={{ display: "inline-block", padding: "1px 7px", borderRadius: 4, fontSize: 10, fontWeight: 700, letterSpacing: "0.05em", background: bg, color, border: `1px solid ${color}33`, fontFamily: "monospace" }}>
      {children}
    </span>
  );
}

// ── Pipeline flow diagram ─────────────────────────────────────────────────────
function FlowDiagram() {
  const box = (label, icon, color, sub) => (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
      <div style={{ padding: "8px 16px", background: `${color}18`, border: `1px solid ${color}44`, borderRadius: 8, textAlign: "center", minWidth: 110 }}>
        <div style={{ fontSize: 14 }}>{icon}</div>
        <div style={{ fontSize: 11, fontWeight: 600, color, marginTop: 2 }}>{label}</div>
        {sub && <div style={{ fontSize: 9, color: "var(--text3)", marginTop: 1 }}>{sub}</div>}
      </div>
    </div>
  );

  const arrow = (label) => (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, padding: "0 4px" }}>
      <div style={{ width: 1, height: 16, background: "var(--border2)" }} />
      <div style={{ fontSize: 8, color: "var(--text3)", whiteSpace: "nowrap" }}>{label}</div>
      <div style={{ fontSize: 10, color: "var(--text3)" }}>▼</div>
    </div>
  );

  const harrow = () => (
    <div style={{ display: "flex", alignItems: "center", padding: "0 6px", paddingTop: 18 }}>
      <div style={{ width: 20, height: 1, background: "var(--border2)" }} />
      <div style={{ fontSize: 10, color: "var(--text3)" }}>▶</div>
    </div>
  );

  return (
    <div style={{ background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 10, padding: "24px 20px", overflowX: "auto" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0, minWidth: 560 }}>

        <div style={{ padding: "6px 20px", background: "rgba(91,106,240,.1)", border: "1px solid rgba(91,106,240,.3)", borderRadius: 6, fontSize: 11, color: "#a5b4fc", fontFamily: "monospace" }}>
          Incident Report (title + description + email)
        </div>

        {arrow("always first")}
        {box("parse_incident", "🔍", "#a5b4fc", "intake")}
        {arrow("parallel fan-out")}

        <div style={{ display: "flex", alignItems: "flex-start", gap: 0, flexWrap: "wrap", justifyContent: "center" }}>
          {box("search_codebase", "💻", "#86efac", "RAG · ChromaDB")}
          {harrow()}
          {box("check_duplicates", "🔁", "#86efac", "embeddings")}
          {harrow()}
          {box("query_metrics", "📊", "#c4b5fd", "SKILL · Prometheus")}
          {harrow()}
          {box("analyze_logs", "📄", "#fb923c", "if log attached")}
          {harrow()}
          {box("analyze_images", "🖼", "#f472b6", "if image attached")}
        </div>

        {arrow("all results in")}
        {box("synthesize_triage", "⚙️", "#fcd34d", "P1–P4 verdict")}

        <div style={{ display: "flex", alignItems: "flex-start", gap: 24, marginTop: 8 }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>
            <div style={{ fontSize: 9, color: "#fca5a5", marginBottom: 4 }}>if P1</div>
            {box("escalate_p1", "🚨", "#fca5a5", "page oncall")}
            {arrow("")}
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0, marginTop: 26 }}>
            <div style={{ fontSize: 9, color: "var(--text3)", marginBottom: 4 }}>if not duplicate</div>
            {box("create_ticket", "🎫", "#a5b4fc", "Jira")}
          </div>
        </div>

        {arrow("always last")}
        {box("send_notifications", "📣", "#fdba74", "email + Slack")}

        <div style={{ marginTop: 8, padding: "4px 14px", background: "rgba(34,197,94,.08)", border: "1px solid rgba(34,197,94,.25)", borderRadius: 5, fontSize: 10, color: "#86efac" }}>
          pipeline_completed → WebSocket → UI
        </div>
      </div>
    </div>
  );
}

// ── Agent cards ───────────────────────────────────────────────────────────────
const AGENTS = [
  {
    id: "parse_incident", icon: "🔍", color: "#a5b4fc", label: "parse_incident",
    role: "Intake & parsing",
    desc: "Always the first tool called. Extracts title, affected service, error type, and symptoms from the free-text incident report. If the information is insufficient, the pipeline terminates here with a clarity request.",
    inputs: ["raw_text", "reporter_email"],
    outputs: ["affected_service", "error_type", "symptoms", "information_sufficient"],
    when: "Always, as the first step.",
  },
  {
    id: "search_codebase", icon: "💻", color: "#86efac", label: "search_codebase",
    role: "Codebase RAG",
    desc: "Searches the ChromaDB semantic index (4,449 chunks from the e-commerce repository) for files and functions most relevant to the incident. Uses OpenAI text-embedding-3-small embeddings. If ChromaDB has no data yet, returns degraded=true and the pipeline continues.",
    inputs: ["query (service + error_type + symptoms)"],
    outputs: ["relevant_files", "analysis_summary", "degraded"],
    when: "Turn 2, in parallel with check_duplicates and query_metrics.",
  },
  {
    id: "check_duplicates", icon: "🔁", color: "#86efac", label: "check_duplicates",
    role: "Semantic deduplication",
    desc: "Computes cosine similarity between the new incident's embedding and historical embeddings in ChromaDB (incident_embeddings collection). If similarity ≥ 0.85, the incident is marked as a duplicate and ticket creation is skipped — only the reporter is notified with a link.",
    inputs: ["incident_text (title + description)"],
    outputs: ["is_duplicate", "highest_similarity", "recommendation", "linked_incident_id"],
    when: "Turn 2, in parallel with search_codebase and query_metrics.",
    thresholds: [
      { value: "≥ 0.95", label: "merge (confirmed duplicate)", color: "#fca5a5" },
      { value: "≥ 0.85", label: "link_existing → skip ticket", color: "#fcd34d" },
      { value: "≥ 0.75", label: "link_existing_soft (suggestion only)", color: "#86efac" },
      { value: "< 0.75",  label: "create_new", color: "#a5b4fc" },
    ],
  },
  {
    id: "query_metrics", icon: "📊", color: "#c4b5fd", label: "query_metrics", skill: true,
    role: "Real-time observability (SKILL)",
    desc: "Specialized skill that queries live metrics for the affected service: error rate, p50/p95 latency, memory usage, and anomaly detection. Values are correlated with incident keywords (timeout, 500, crash → degraded metrics). In production this would call Prometheus/Grafana. Results enrich the triage verdict.",
    inputs: ["service", "window_minutes"],
    outputs: ["error_rate", "p50_latency_ms", "p95_latency_ms", "memory_usage_pct", "anomaly_detected"],
    when: "Turn 2, in parallel with search_codebase and check_duplicates.",
  },
  {
    id: "synthesize_triage", icon: "⚙️", color: "#fcd34d", label: "synthesize_triage",
    role: "Synthesis & verdict",
    desc: "The core reasoning agent. With all collected data (parsed incident, relevant code, historical similarity, live metrics), produces the final verdict: P1–P4 severity, confidence score, root cause hypothesis, investigation steps, and a remediation runbook with real shell/kubectl/SQL commands.",
    inputs: ["parsed_incident", "code_analysis", "dedup_result", "metrics_result"],
    outputs: ["severity", "confidence", "root_cause_hypothesis", "investigation_steps", "runbook", "suggested_assignee_team", "needs_human_review"],
    when: "Turn 3, after all three parallel tools complete.",
    rules: [
      "P1 + confidence < 0.5 → auto-downgrade to P2 + needs_human_review=true",
      "confidence < 0.6 → needs_human_review=true (no severity downgrade)",
    ],
  },
  {
    id: "escalate_p1", icon: "🚨", color: "#fca5a5", label: "escalate_p1",
    role: "P1 fast-path",
    desc: "Only called when severity=P1. Sets the escalation flag in state, emits an urgent WebSocket event, and records the paged team. Claude calls this tool BEFORE create_ticket so the subsequent notification includes the urgency flag.",
    inputs: ["title", "assignee_team"],
    outputs: ["escalated: true", "team_paged"],
    when: "Only if severity=P1, before create_ticket.",
  },
  {
    id: "create_ticket", icon: "🎫", color: "#a5b4fc", label: "create_ticket",
    role: "Jira ticket creation",
    desc: "Creates a ticket in the Jira mock with priority mapped from severity (P1→Critical, P2→High, P3→Medium, P4→Low). Skipped if the incident is a confirmed duplicate (similarity ≥ 0.85). On failure returns ticket_id=MANUAL-REQUIRED — the pipeline does not abort.",
    inputs: ["triage_verdict", "parsed_incident", "code_analysis"],
    outputs: ["ticket_id", "ticket_url"],
    when: "If NOT duplicate. After escalate_p1 for P1 incidents.",
    priority: ["P1 → Critical", "P2 → High", "P3 → Medium", "P4 → Low"],
  },
  {
    id: "send_notifications", icon: "📣", color: "#fdba74", label: "send_notifications",
    role: "Notifications",
    desc: "Sends three notifications concurrently via asyncio.gather: team email, reporter email, and a Slack message. If escalation_triggered=true, the subject line is 🚨 [CRITICAL] and Slack includes @oncall. For duplicates, the reporter receives a 'linked to existing incident' email instead of the full triage summary.",
    inputs: ["triage_verdict", "ticket_id", "reporter_email", "escalation_triggered", "dedup_result"],
    outputs: ["notifications_sent: ['team_email', 'reporter_email', 'slack']"],
    when: "Always, as the final step.",
  },
  {
    id: "analyze_logs", icon: "📄", color: "#fb923c", label: "analyze_logs",
    role: "Log file analysis",
    desc: "Activated automatically when the incident includes log or text attachments (.log, .txt, .csv, .json, .yaml). Uses Claude Haiku to scan all attached files in a single pass — extracting top errors, exception types, frequencies, timestamps, and anomalous patterns. Results are passed to synthesize_triage to improve root cause accuracy.",
    inputs: ["focus (optional hint)", "attachments from state (type=text)"],
    outputs: ["files_analyzed", "file_count", "analysis (error patterns, stack traces, anomalies)"],
    when: "Turn 2 in parallel — ONLY if log/text attachments are present.",
  },
  {
    id: "analyze_images", icon: "🖼", color: "#f472b6", label: "analyze_images",
    role: "Image visual analysis",
    desc: "Activated automatically when the incident includes image attachments (.png, .jpg, .jpeg, .gif). Uses Claude Haiku vision to analyze all images in a single turn — reading error dialogs, Grafana/dashboard screenshots, flamegraphs, CPU/memory graphs, or UI error states. Results are passed to synthesize_triage to enrich the verdict.",
    inputs: ["focus (optional hint)", "attachments from state (type=image)"],
    outputs: ["images_analyzed", "image_count", "analysis (extracted errors, metric values, visual anomalies)"],
    when: "Turn 2 in parallel — ONLY if image attachments are present.",
  },
];

function AgentCard({ agent }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden", marginBottom: 8 }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{ padding: "10px 14px", display: "flex", alignItems: "center", gap: 10, cursor: "pointer", userSelect: "none" }}
      >
        <span style={{ fontSize: 16 }}>{agent.icon}</span>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <code style={{ fontSize: 12, color: agent.color, fontFamily: "'JetBrains Mono',monospace", fontWeight: 600 }}>{agent.label}</code>
            {agent.skill && <Tag color="#c4b5fd" bg="rgba(196,181,253,.1)">SKILL</Tag>}
            <span style={{ fontSize: 11, color: "var(--text3)" }}>{agent.role}</span>
          </div>
        </div>
        <span style={{ fontSize: 11, color: "var(--text3)", transform: open ? "rotate(180deg)" : "none", transition: "transform .2s" }}>▾</span>
      </div>

      {open && (
        <div style={{ padding: "0 14px 14px", borderTop: "1px solid var(--border)" }}>
          <p style={{ fontSize: 12, color: "var(--text2)", lineHeight: 1.7, margin: "12px 0" }}>{agent.desc}</p>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 5 }}>Inputs</div>
              {agent.inputs.map((i, idx) => <div key={idx} style={{ fontSize: 11, color: "var(--text2)", fontFamily: "monospace", marginBottom: 2 }}>· {i}</div>)}
            </div>
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 5 }}>Outputs</div>
              {agent.outputs.map((o, idx) => <div key={idx} style={{ fontSize: 11, color: "var(--text2)", fontFamily: "monospace", marginBottom: 2 }}>· {o}</div>)}
            </div>
          </div>

          <div style={{ fontSize: 11, color: "var(--text3)", background: "var(--surface2)", border: "1px solid var(--border)", borderRadius: 5, padding: "6px 10px", marginBottom: agent.thresholds || agent.rules || agent.priority ? 10 : 0 }}>
            <span style={{ fontWeight: 600 }}>When called: </span>{agent.when}
          </div>

          {agent.thresholds && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>Similarity thresholds</div>
              {agent.thresholds.map((t, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <code style={{ fontSize: 10, color: t.color, fontFamily: "monospace", minWidth: 50 }}>{t.value}</code>
                  <span style={{ fontSize: 11, color: "var(--text2)" }}>→ {t.label}</span>
                </div>
              ))}
            </div>
          )}

          {agent.rules && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>Coherence rules</div>
              {agent.rules.map((r, i) => (
                <div key={i} style={{ fontSize: 11, color: "#fcd34d", fontFamily: "monospace", marginBottom: 3 }}>⚠ {r}</div>
              ))}
            </div>
          )}

          {agent.priority && (
            <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
              {agent.priority.map((p, i) => <Tag key={i} color="#a5b4fc">{p}</Tag>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Decision logic table ──────────────────────────────────────────────────────
const DECISIONS = [
  { condition: "similarity ≥ 0.85", action: "Skip create_ticket → notify reporter with link to existing incident only", color: "#fcd34d" },
  { condition: "severity = P1", action: "Call escalate_p1 before create_ticket → 🚨 [CRITICAL] email subject + @oncall Slack mention", color: "#fca5a5" },
  { condition: "P1 + confidence < 0.5", action: "Auto-downgrade to P2 + needs_human_review = true", color: "#fca5a5" },
  { condition: "confidence < 0.6", action: "Set needs_human_review = true (no severity downgrade)", color: "#fcd34d" },
  { condition: "information_sufficient = false", action: "Terminate pipeline with request_clarity — no triage performed", color: "var(--text3)" },
  { condition: "anomaly_detected = true (query_metrics)", action: "Metric data included in synthesize_triage context to inform higher severity", color: "#c4b5fd" },
  { condition: "code_analysis.degraded = true", action: "Pipeline continues without code data — partial-information triage", color: "var(--text3)" },
  { condition: "create_ticket fails", action: "ticket_id = MANUAL-REQUIRED — pipeline does not abort", color: "var(--text3)" },
  { condition: "log/text attachments present", action: "analyze_logs called in parallel at turn 2 — error patterns and stack traces injected into synthesize_triage context", color: "#fb923c" },
  { condition: "image attachments present", action: "analyze_images called in parallel at turn 2 — visual anomalies and extracted errors injected into synthesize_triage context", color: "#f472b6" },
];

function DecisionTable() {
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ padding: "8px 14px", textAlign: "left", fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.07em", borderBottom: "1px solid var(--border)", width: "40%" }}>Condition</th>
            <th style={{ padding: "8px 14px", textAlign: "left", fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.07em", borderBottom: "1px solid var(--border)" }}>System decision</th>
          </tr>
        </thead>
        <tbody>
          {DECISIONS.map((d, i) => (
            <tr key={i} style={{ borderBottom: i < DECISIONS.length - 1 ? "1px solid var(--border)" : "none" }}>
              <td style={{ padding: "10px 14px", verticalAlign: "top" }}>
                <code style={{ fontSize: 11, color: d.color, fontFamily: "'JetBrains Mono',monospace", lineHeight: 1.5 }}>{d.condition}</code>
              </td>
              <td style={{ padding: "10px 14px", fontSize: 12, color: "var(--text2)", lineHeight: 1.6, verticalAlign: "top" }}>
                {d.action}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── ReAct loop explanation ────────────────────────────────────────────────────
function LoopExplanation() {
  const steps = [
    { n: 1, title: "Claude receives the incident", desc: "The model receives the incident text (with any attachments inline) and the schemas for all 10 available tools. There is no hardcoded routing — Claude reasons about what to do next." },
    { n: 2, title: "Claude emits tool_use blocks", desc: "Responds with one or more tool_use blocks. It calls multiple tools in a single turn: search_codebase + check_duplicates + query_metrics always, plus analyze_logs if log/text files are attached, and analyze_images if image files are attached." },
    { n: 3, title: "Parallel execution", desc: "asyncio.gather runs all tools in the turn simultaneously. Each tool emits agent_started and agent_completed events over WebSocket in real time." },
    { n: 4, title: "Results → context", desc: "Results are appended to the message history as tool_result content blocks. Claude reads them in the next turn to inform its next decision." },
    { n: 5, title: "Loop until end_turn", desc: "Repeats until Claude stops calling tools (stop_reason=end_turn) or the 15-iteration safety cap is hit. In practice the pipeline completes in 5–7 turns." },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {steps.map(s => (
        <div key={s.n} style={{ display: "flex", gap: 14, padding: "12px 14px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8 }}>
          <div style={{ flexShrink: 0, width: 24, height: 24, borderRadius: 6, background: "rgba(91,106,240,.15)", border: "1px solid rgba(91,106,240,.3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#a5b4fc" }}>{s.n}</div>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", marginBottom: 3 }}>{s.title}</div>
            <div style={{ fontSize: 12, color: "var(--text3)", lineHeight: 1.6 }}>{s.desc}</div>
          </div>
        </div>
      ))}
      <div style={{ marginTop: 4, padding: "10px 14px", background: "rgba(91,106,240,.06)", border: "1px solid rgba(91,106,240,.2)", borderRadius: 7, fontSize: 12, color: "var(--text2)", lineHeight: 1.65 }}>
        <strong style={{ color: "#a5b4fc" }}>Visible reasoning:</strong> The text Claude generates between tool calls is captured and shown in the left panel of each incident view — in italics, before the tool calls of each turn. You can see exactly why it decided to call each tool.
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function SystemDocs() {
  return (
    <div style={{ maxWidth: 860, margin: "0 auto" }}>
      <div style={{ marginBottom: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em" }}>System Architecture</h1>
          <span style={{ padding: "2px 10px", background: "rgba(91,106,240,.12)", border: "1px solid rgba(91,106,240,.25)", borderRadius: 5, fontSize: 11, color: "#a5b4fc", fontFamily: "monospace" }}>ReAct · claude-sonnet-4-6</span>
        </div>
        <p style={{ fontSize: 13, color: "var(--text2)", lineHeight: 1.7, maxWidth: 640 }}>
          Incident Cortex uses the <strong style={{ color: "var(--text)" }}>ReAct (Reasoning + Acting)</strong> pattern with Anthropic's native tool use API.
          Instead of a fixed graph, Claude autonomously reasons about which tools to call and in what order,
          based on the accumulated results of each turn. The full pipeline completes in ~15 seconds.
        </p>
        <div style={{ display: "flex", gap: 10, marginTop: 14, flexWrap: "wrap" }}>
          {[
            ["10 tools", "#a5b4fc"], ["parallel turn 2", "#86efac"],
            ["max 15 iterations", "#fcd34d"], ["real-time WebSocket", "#fdba74"],
            ["RAG · ChromaDB · 4449 chunks", "#86efac"], ["semantic deduplication", "#c4b5fd"],
            ["log analysis", "#fb923c"], ["image vision", "#f472b6"],
          ].map(([label, color]) => (
            <Tag key={label} color={color}>{label}</Tag>
          ))}
        </div>
      </div>

      <Section title="Pipeline Flow">
        <FlowDiagram />
      </Section>

      <Section title="ReAct Loop — How it works">
        <LoopExplanation />
      </Section>

      <Section title="Agents & Tools — click to expand">
        {AGENTS.map(a => <AgentCard key={a.id} agent={a} />)}
      </Section>

      <Section title="Decision Logic">
        <DecisionTable />
      </Section>

      <Section title="Tech Stack">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
          {[
            { layer: "Orchestration", items: ["Claude Sonnet 4.6", "Anthropic Tool Use API", "asyncio.gather (parallel)", "ReAct loop (max 15 turns)"] },
            { layer: "Data & Search", items: ["ChromaDB 0.5.23", "OpenAI text-embedding-3-small", "Sentence Transformers (fallback)", "PostgreSQL (event store)"] },
            { layer: "Infrastructure", items: ["FastAPI + uvicorn", "WebSocket (real-time events)", "React 18 + CRA", "Docker Compose (8 services)"] },
            { layer: "Mocks & Notifications", items: ["Jira Mock (FastAPI + SQLite)", "Slack Mock (FastAPI + SQLite)", "MailHog (SMTP)"] },
            { layer: "Observability", items: ["Langfuse (LLM tracing)", "OpenTelemetry spans", "EventStore (pipeline history)", "GET /api/metrics"] },
            { layer: "Indexing", items: ["1,605 files indexed", "4,449 chunks in ChromaDB", "Reaction Commerce repo", "One-shot indexer container"] },
          ].map(({ layer, items }) => (
            <div key={layer} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 14px" }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 8 }}>{layer}</div>
              {items.map(item => (
                <div key={item} style={{ fontSize: 11, color: "var(--text2)", marginBottom: 4, display: "flex", alignItems: "flex-start", gap: 5 }}>
                  <span style={{ color: "var(--text3)", flexShrink: 0, marginTop: 1 }}>·</span>{item}
                </div>
              ))}
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
