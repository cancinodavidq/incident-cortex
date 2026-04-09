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

        {/* Incident input */}
        <div style={{ padding: "6px 20px", background: "rgba(91,106,240,.1)", border: "1px solid rgba(91,106,240,.3)", borderRadius: 6, fontSize: 11, color: "#a5b4fc", fontFamily: "monospace" }}>
          Incident Report (title + description + email)
        </div>

        {arrow("always first")}
        {box("parse_incident", "🔍", "#a5b4fc", "intake")}
        {arrow("parallel fan-out")}

        {/* Parallel turn */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: 0 }}>
          {box("search_codebase", "💻", "#86efac", "RAG · ChromaDB")}
          {harrow()}
          {box("check_duplicates", "🔁", "#86efac", "embeddings")}
          {harrow()}
          {box("query_metrics", "📊", "#c4b5fd", "SKILL · Prometheus")}
        </div>

        {arrow("all results in")}
        {box("synthesize_triage", "⚙️", "#fcd34d", "P1–P4 verdict")}

        {/* Conditional branch */}
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
    desc: "Primer tool que se llama siempre. Extrae título, servicio afectado, tipo de error y síntomas del texto libre del reporte. Si la información es insuficiente, el pipeline termina aquí con una solicitud de clarificación.",
    inputs: ["raw_text", "reporter_email"],
    outputs: ["affected_service", "error_type", "symptoms", "information_sufficient"],
    when: "Siempre, como primer paso.",
  },
  {
    id: "search_codebase", icon: "💻", color: "#86efac", label: "search_codebase",
    role: "RAG sobre codebase",
    desc: "Busca en el índice semántico de ChromaDB (4,449 chunks del repositorio e-commerce) los archivos y funciones más relevantes al incidente. Usa embeddings de OpenAI text-embedding-3-small. Si ChromaDB no tiene datos aún, retorna degraded=true y el pipeline continúa.",
    inputs: ["query (service + error_type + symptoms)"],
    outputs: ["relevant_files", "analysis_summary", "degraded"],
    when: "Turn 2, en paralelo con check_duplicates y query_metrics.",
  },
  {
    id: "check_duplicates", icon: "🔁", color: "#86efac", label: "check_duplicates",
    role: "Deduplicación semántica",
    desc: "Calcula la similitud coseno entre el embedding del incidente nuevo y los embeddings históricos en ChromaDB (colección incident_embeddings). Si similarity ≥ 0.85, el incidente se marca como duplicado y se omite la creación de ticket — solo se notifica al reporter.",
    inputs: ["incident_text (title + description)"],
    outputs: ["is_duplicate", "highest_similarity", "recommendation", "linked_incident_id"],
    when: "Turn 2, en paralelo con search_codebase y query_metrics.",
    thresholds: [
      { value: "≥ 0.95", label: "merge", color: "#fca5a5" },
      { value: "≥ 0.85", label: "link_existing → skip ticket", color: "#fcd34d" },
      { value: "≥ 0.75", label: "link_existing_soft (sugerencia)", color: "#86efac" },
      { value: "< 0.75", label: "create_new", color: "#a5b4fc" },
    ],
  },
  {
    id: "query_metrics", icon: "📊", color: "#c4b5fd", label: "query_metrics", skill: true,
    role: "Observabilidad en tiempo real (SKILL)",
    desc: "Skill especializado que consulta métricas del servicio afectado: error rate, latencia p50/p95, memoria, y detección de anomalías. Los valores están correlacionados con las keywords del incidente (timeout, 500, crash → métricas degradadas). En producción conectaría a Prometheus/Grafana. Los resultados enriquecen el veredicto de triage.",
    inputs: ["service", "window_minutes"],
    outputs: ["error_rate", "p50_latency_ms", "p95_latency_ms", "memory_usage_pct", "anomaly_detected"],
    when: "Turn 2, en paralelo con search_codebase y check_duplicates.",
  },
  {
    id: "synthesize_triage", icon: "⚙️", color: "#fcd34d", label: "synthesize_triage",
    role: "Síntesis y veredicto",
    desc: "El corazón del sistema. Con todos los datos recolectados (parsed incident, código relevante, similitud histórica, métricas), produce el veredicto final: severidad P1-P4, hipótesis de causa raíz, pasos de investigación, y un runbook de remediación con comandos reales (kubectl, SQL, bash).",
    inputs: ["parsed_incident", "code_analysis", "dedup_result", "metrics_result"],
    outputs: ["severity", "confidence", "root_cause_hypothesis", "investigation_steps", "runbook", "suggested_assignee_team", "needs_human_review"],
    when: "Turn 3, después de que los tres tools paralelos terminen.",
    rules: [
      "P1 + confidence < 0.5 → auto-degrada a P2 + needs_human_review=true",
      "confidence < 0.6 → needs_human_review=true",
    ],
  },
  {
    id: "escalate_p1", icon: "🚨", color: "#fca5a5", label: "escalate_p1",
    role: "Fast-path P1",
    desc: "Solo se llama cuando severity=P1. Marca el estado de escalación, emite un evento urgente por WebSocket, y registra el equipo paginado. Claude llama este tool ANTES de create_ticket para que la notificación posterior incluya el flag de urgencia.",
    inputs: ["title", "assignee_team"],
    outputs: ["escalated: true", "team_paged"],
    when: "Solo si severity=P1, antes de create_ticket.",
  },
  {
    id: "create_ticket", icon: "🎫", color: "#a5b4fc", label: "create_ticket",
    role: "Jira ticket",
    desc: "Crea un ticket en el Jira mock con prioridad mapeada a la severidad (P1→Critical, P2→High, P3→Medium, P4→Low). Se omite si el incidente es un duplicado confirmado (similarity ≥ 0.85). En caso de fallo retorna MANUAL-REQUIRED.",
    inputs: ["triage_verdict", "parsed_incident", "code_analysis"],
    outputs: ["ticket_id", "ticket_url"],
    when: "Si NOT duplicate. Después de escalate_p1 si es P1.",
    priority: ["P1 → Critical", "P2 → High", "P3 → Medium", "P4 → Low"],
  },
  {
    id: "send_notifications", icon: "📣", color: "#fdba74", label: "send_notifications",
    role: "Notificaciones",
    desc: "Envía en paralelo (asyncio.gather): email al equipo, email al reporter, y mensaje a Slack. Si escalation_triggered=true, el subject es 🚨 [CRITICAL] y el mensaje de Slack incluye @oncall. Si es duplicado, el reporter recibe un email de 'linked to existing' en lugar del resumen completo.",
    inputs: ["triage_verdict", "ticket_id", "reporter_email", "escalation_triggered", "dedup_result"],
    outputs: ["notifications_sent: ['team_email', 'reporter_email', 'slack']"],
    when: "Siempre, como último paso.",
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
            <span style={{ fontWeight: 600 }}>Cuándo se llama: </span>{agent.when}
          </div>

          {agent.thresholds && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>Umbrales de similitud</div>
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
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>Reglas de coherencia</div>
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
  { condition: "similarity ≥ 0.85", action: "Omitir create_ticket → solo notificar con link al incidente existente", color: "#fcd34d" },
  { condition: "severity = P1", action: "Llamar escalate_p1 antes de create_ticket → subject 🚨 [CRITICAL] en email y @oncall en Slack", color: "#fca5a5" },
  { condition: "P1 + confidence < 0.5", action: "Auto-degradar a P2 + needs_human_review = true", color: "#fca5a5" },
  { condition: "confidence < 0.6", action: "needs_human_review = true (sin degradar severidad)", color: "#fcd34d" },
  { condition: "information_sufficient = false", action: "Terminar pipeline con request_clarity (sin triage)", color: "var(--text3)" },
  { condition: "anomaly_detected = true en query_metrics", action: "Datos de métricas incluidos en contexto de synthesize_triage para elevar severidad", color: "#c4b5fd" },
  { condition: "code_analysis.degraded = true", action: "Pipeline continúa sin datos de código — triage con información parcial", color: "var(--text3)" },
  { condition: "create_ticket falla", action: "ticket_id = MANUAL-REQUIRED — pipeline no aborta", color: "var(--text3)" },
];

function DecisionTable() {
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ padding: "8px 14px", textAlign: "left", fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.07em", borderBottom: "1px solid var(--border)", width: "40%" }}>Condición</th>
            <th style={{ padding: "8px 14px", textAlign: "left", fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.07em", borderBottom: "1px solid var(--border)" }}>Decisión del sistema</th>
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
    { n: 1, title: "Claude recibe el incidente", desc: "El modelo recibe el texto del reporte y los schemas de los 8 tools disponibles. No hay routing hardcodeado — Claude razona qué hacer." },
    { n: 2, title: "Claude emite tool_use blocks", desc: "Responde con uno o más bloques tool_use. Puede llamar múltiples tools en un mismo turno (search_codebase + check_duplicates + query_metrics en paralelo)." },
    { n: 3, title: "Ejecución paralela", desc: "asyncio.gather ejecuta todos los tools del turno simultáneamente. Cada tool emite agent_started y agent_completed por WebSocket en tiempo real." },
    { n: 4, title: "Resultados → contexto", desc: "Los resultados se agregan al historial de mensajes como tool_result content blocks. Claude los lee en el siguiente turno." },
    { n: 5, title: "Loop hasta end_turn", desc: "Se repite hasta que Claude decide no llamar más tools (stop_reason=end_turn) o se alcanza el máximo de 15 iteraciones. En la práctica termina en 5-7 turnos." },
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
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function SystemDocs() {
  return (
    <div style={{ maxWidth: 860, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em" }}>System Architecture</h1>
          <span style={{ padding: "2px 10px", background: "rgba(91,106,240,.12)", border: "1px solid rgba(91,106,240,.25)", borderRadius: 5, fontSize: 11, color: "#a5b4fc", fontFamily: "monospace" }}>ReAct · claude-sonnet-4-6</span>
        </div>
        <p style={{ fontSize: 13, color: "var(--text2)", lineHeight: 1.7, maxWidth: 640 }}>
          Incident Cortex usa el patrón <strong style={{ color: "var(--text)" }}>ReAct (Reasoning + Acting)</strong> con la API nativa de tool use de Anthropic.
          En lugar de un grafo fijo, Claude razona autónomamente sobre qué tools llamar y en qué orden,
          basándose en los resultados acumulados de cada turno. El pipeline completo tarda ~15 segundos.
        </p>

        <div style={{ display: "flex", gap: 10, marginTop: 14, flexWrap: "wrap" }}>
          {[
            ["8 tools", "#a5b4fc"], ["paralelo en turn 2", "#86efac"],
            ["máx 15 iteraciones", "#fcd34d"], ["WebSocket en tiempo real", "#fdba74"],
            ["RAG · ChromaDB · 4449 chunks", "#86efac"], ["deduplicación semántica", "#c4b5fd"],
          ].map(([label, color]) => (
            <Tag key={label} color={color}>{label}</Tag>
          ))}
        </div>
      </div>

      <Section title="Pipeline Flow">
        <FlowDiagram />
      </Section>

      <Section title="ReAct Loop — Cómo funciona">
        <LoopExplanation />
        <div style={{ marginTop: 12, padding: "10px 14px", background: "rgba(91,106,240,.06)", border: "1px solid rgba(91,106,240,.2)", borderRadius: 7, fontSize: 12, color: "var(--text2)", lineHeight: 1.65 }}>
          <strong style={{ color: "#a5b4fc" }}>Razonamiento visible:</strong> El texto que Claude genera entre tool calls (su razonamiento) se captura y se muestra en el panel izquierdo de cada incidente — en cursiva, antes de los tool calls de cada turno. Puedes ver exactamente por qué decidió llamar cada herramienta.
        </div>
      </Section>

      <Section title="Agentes y Tools — click para expandir">
        {AGENTS.map(a => <AgentCard key={a.id} agent={a} />)}
      </Section>

      <Section title="Lógica de Decisión">
        <DecisionTable />
      </Section>

      <Section title="Stack Técnico">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
          {[
            { layer: "Orquestación", items: ["Claude Sonnet 4.6", "Anthropic Tool Use API", "asyncio.gather (paralelo)", "ReAct loop (máx 15 turns)"] },
            { layer: "Datos & Búsqueda", items: ["ChromaDB 0.5.23", "OpenAI text-embedding-3-small", "Sentence Transformers (fallback)", "PostgreSQL (event store)"] },
            { layer: "Infraestructura", items: ["FastAPI + uvicorn", "WebSocket (eventos en tiempo real)", "React 18 + CRA", "Docker Compose (8 servicios)"] },
            { layer: "Mocks & Notificaciones", items: ["Jira Mock (FastAPI + SQLite)", "Slack Mock (FastAPI + SQLite)", "MailHog (SMTP)"] },
            { layer: "Observabilidad", items: ["Langfuse (LLM tracing)", "OpenTelemetry spans", "EventStore (pipeline history)", "GET /api/metrics"] },
            { layer: "Indexación", items: ["1,605 archivos indexados", "4,449 chunks en ChromaDB", "Reaction Commerce repo", "one-shot indexer container"] },
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
