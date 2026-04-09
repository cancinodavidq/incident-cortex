import React, { useState, useEffect } from "react";
import { useWebSocket } from "../hooks/useWebSocket";

// ── Design tokens ─────────────────────────────────────────────────────────────
const SEV = {
  P1: { bg:"rgba(239,68,68,.1)",  border:"rgba(239,68,68,.35)",  badge:"#ef4444", badgeText:"#fff",    label:"Critical"  },
  P2: { bg:"rgba(249,115,22,.1)", border:"rgba(249,115,22,.35)", badge:"#f97316", badgeText:"#fff",    label:"High"      },
  P3: { bg:"rgba(234,179,8,.1)",  border:"rgba(234,179,8,.35)",  badge:"#eab308", badgeText:"#000",    label:"Medium"    },
  P4: { bg:"rgba(34,197,94,.1)",  border:"rgba(34,197,94,.35)",  badge:"#22c55e", badgeText:"#000",    label:"Low"       },
};

const AGENTS = [
  { id:"intake",        icon:"🔍", label:"Parse Report"     },
  { id:"code_analysis", icon:"💻", label:"Code Analysis"    },
  { id:"dedup",         icon:"🔁", label:"Dedup Check"      },
  { id:"triage_synth",  icon:"⚙️", label:"Triage Synthesis" },
  { id:"escalate",      icon:"🚨", label:"P1 Escalation",  conditional:true },
  { id:"ticket",        icon:"🎫", label:"Create Ticket"    },
  { id:"notify",        icon:"📣", label:"Notifications"    },
];

const PARALLEL = new Set(["code_analysis","dedup"]);

function cleanStep(s) { return s.replace(/^\d+\.\d*\s*/, "").replace(/^[-•]\s*/, "").trim(); }

// ── Status dot ────────────────────────────────────────────────────────────────
function StatusDot({ status }) {
  if (status === "running") return (
    <span style={{ display:"flex", alignItems:"center", justifyContent:"center", width:18, height:18, flexShrink:0 }}>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <span style={{ width:12, height:12, border:"2px solid var(--accent)", borderTopColor:"transparent", borderRadius:"50%", display:"inline-block", animation:"spin .7s linear infinite" }} />
    </span>
  );
  if (status === "done") return (
    <span style={{ width:18, height:18, borderRadius:"50%", background:"rgba(34,197,94,.2)", border:"1px solid rgba(34,197,94,.4)", display:"flex", alignItems:"center", justifyContent:"center", flexShrink:0, fontSize:9, color:"var(--green)" }}>✓</span>
  );
  return (
    <span style={{ width:18, height:18, borderRadius:"50%", border:"1px solid var(--border2)", display:"flex", alignItems:"center", justifyContent:"center", flexShrink:0 }} />
  );
}

// ── Inline result per agent ───────────────────────────────────────────────────
function AgentResult({ id, data }) {
  if (!data) return null;
  const s = { fontSize:11, color:"var(--text3)", marginTop:2 };

  if (id === "intake") {
    if (data.information_sufficient === false)
      return <div style={{...s, color:"#fcd34d"}}>⚠ Needs clarification</div>;
    const parts = [data.affected_service, data.error_type].filter(Boolean);
    return <div style={s}>{parts.join(" · ") || "Parsed"}</div>;
  }
  if (id === "code_analysis") {
    const n = data.relevant_files?.length || 0;
    return <div style={s}>{n ? `${n} file${n>1?"s":""} identified` : "No files found"}</div>;
  }
  if (id === "dedup") {
    const sim = Math.round((data.highest_similarity||0)*100);
    return <div style={{...s, color: data.is_duplicate ? "#fcd34d" : "var(--green)"}}>
      {data.is_duplicate ? `Duplicate · ${sim}% match` : `New · ${sim}% max similarity`}
    </div>;
  }
  if (id === "triage_synth") {
    if (!data.severity) return <div style={{...s}}>Skipped</div>;
    const sev = SEV[data.severity] || SEV.P3;
    return (
      <div style={{ display:"flex", alignItems:"center", gap:6, marginTop:2 }}>
        <span style={{ background:sev.badge, color:sev.badgeText, padding:"1px 6px", borderRadius:4, fontSize:11, fontWeight:700 }}>{data.severity}</span>
        <span style={s}>{Math.round((data.confidence||0)*100)}% confidence</span>
      </div>
    );
  }
  if (id === "ticket") {
    return data.ticket_id
      ? <div style={{...s, color:"var(--accent)", fontFamily:"monospace"}}>{data.ticket_id}</div>
      : <div style={s}>No ticket</div>;
  }
  if (id === "notify") {
    const sent = data.notifications_sent || [];
    return <div style={s}>{sent.length ? sent.map(n => n.replace("_email"," email")).join(", ") : "None sent"}</div>;
  }
  return null;
}

// ── Pipeline panel ────────────────────────────────────────────────────────────
function PipelinePanel({ agentState }) {
  const st = (id) => agentState[id] || { status:"pending", result:null };

  const rowStyle = (status) => ({
    display:"flex", alignItems:"flex-start", gap:10, padding:"9px 14px", borderRadius:7,
    background: status==="running" ? "rgba(91,106,240,.08)" : "transparent",
    transition:"background .2s",
  });

  const labelStyle = (status) => ({
    fontSize:13, fontWeight:500, color:
      status==="running" ? "var(--text)" :
      status==="done"    ? "var(--text)" : "var(--text3)",
    lineHeight:1,
  });

  const renderRow = (a) => {
    const { status, result } = st(a.id);
    // Only show conditional (escalate) row if it ran
    if (a.conditional && status === "pending") return null;
    return (
      <div key={a.id} style={rowStyle(status)}>
        <div style={{ paddingTop:2 }}><StatusDot status={status} /></div>
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{ display:"flex", alignItems:"center", gap:8 }}>
            <span style={{ fontSize:13 }}>{a.icon}</span>
            <span style={labelStyle(status)}>{a.label}</span>
            {status==="running" && <span style={{ fontSize:11, color:"var(--accent)", opacity:.8 }}>running</span>}
          </div>
          <AgentResult id={a.id} data={result} />
        </div>
      </div>
    );
  };

  const seq1    = AGENTS.filter(a => a.id === "intake");
  const par     = AGENTS.filter(a => PARALLEL.has(a.id));
  const seq2    = AGENTS.filter(a => !PARALLEL.has(a.id) && a.id !== "intake");
  const divider = <div style={{ height:1, background:"var(--border)", margin:"4px 0" }} />;
  const parLabel = (
    <div style={{ display:"flex", alignItems:"center", gap:8, padding:"4px 14px" }}>
      <div style={{ flex:1, height:1, background:"var(--border)" }} />
      <span style={{ fontSize:10, color:"var(--text3)", fontWeight:600, letterSpacing:"0.08em", textTransform:"uppercase" }}>parallel</span>
      <div style={{ flex:1, height:1, background:"var(--border)" }} />
    </div>
  );

  return (
    <div style={{ background:"var(--surface)", border:"1px solid var(--border)", borderRadius:10, overflow:"hidden" }}>
      <div style={{ padding:"10px 14px 8px", borderBottom:"1px solid var(--border)" }}>
        <span style={{ fontSize:11, fontWeight:600, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.07em" }}>Pipeline</span>
      </div>
      <div style={{ padding:"6px 0" }}>
        {seq1.map(renderRow)}
        {divider}
        {parLabel}
        {par.map(renderRow)}
        {divider}
        {seq2.map(renderRow)}
      </div>
    </div>
  );
}

// ── Triage result card ────────────────────────────────────────────────────────
function TriageCard({ verdict, summary, isDuplicate }) {
  if (!verdict?.severity) return null;
  const sev = SEV[verdict.severity] || SEV.P3;
  const steps = verdict.investigation_steps || [];
  const notifications = summary?.notifications_sent || [];
  const confidence = Math.round((verdict.confidence||0)*100);

  return (
    <div style={{ background:"var(--surface)", border:`1px solid ${sev.border}`, borderRadius:10, overflow:"hidden" }}>
      {/* Severity bar */}
      <div style={{ background:sev.bg, borderBottom:`1px solid ${sev.border}`, padding:"16px 20px", display:"flex", alignItems:"center", justifyContent:"space-between", gap:16 }}>
        <div style={{ display:"flex", alignItems:"center", gap:12 }}>
          <span style={{ background:sev.badge, color:sev.badgeText, padding:"4px 12px", borderRadius:6, fontSize:15, fontWeight:800, letterSpacing:"-0.01em" }}>
            {verdict.severity}
          </span>
          <div>
            <div style={{ fontSize:14, fontWeight:600, color:"var(--text)" }}>
              {isDuplicate ? "Duplicate incident" : sev.label + " severity"}
            </div>
            <div style={{ fontSize:12, color:"var(--text3)", marginTop:1 }}>
              {confidence}% confidence{verdict.needs_human_review ? " · Human review flagged" : ""}
            </div>
          </div>
        </div>
        {(summary?.ticket_id || notifications.length > 0) && (
          <div style={{ display:"flex", alignItems:"center", gap:10, flexShrink:0 }}>
            {summary?.ticket_id && (
              <a
                href={`http://localhost:8081/browse/${summary.ticket_id}`}
                target="_blank" rel="noopener noreferrer"
                style={{ padding:"5px 12px", background:"rgba(91,106,240,.15)", border:"1px solid rgba(91,106,240,.3)", borderRadius:6, fontSize:12, fontWeight:600, color:"#a5b4fc", fontFamily:"monospace", whiteSpace:"nowrap" }}
              >
                {summary.ticket_id}
              </a>
            )}
          </div>
        )}
      </div>

      <div style={{ padding:"20px" }}>
        {/* Root cause */}
        {verdict.root_cause_hypothesis && (
          <div style={{ marginBottom:24 }}>
            <div style={{ fontSize:11, fontWeight:700, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.08em", marginBottom:8 }}>Root Cause</div>
            <p style={{ fontSize:14, color:"var(--text)", lineHeight:1.65 }}>{verdict.root_cause_hypothesis}</p>
          </div>
        )}

        {/* Investigation steps */}
        {steps.length > 0 && (
          <div style={{ marginBottom:20 }}>
            <div style={{ fontSize:11, fontWeight:700, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.08em", marginBottom:12 }}>Investigation Steps</div>
            <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
              {steps.map((step, i) => (
                <div key={i} style={{ display:"flex", gap:12, alignItems:"flex-start" }}>
                  <span style={{ flexShrink:0, width:22, height:22, borderRadius:5, background:"var(--surface2)", border:"1px solid var(--border2)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:11, fontWeight:700, color:"var(--text3)", marginTop:1 }}>
                    {i+1}
                  </span>
                  <p style={{ fontSize:13, color:"var(--text2)", lineHeight:1.6, paddingTop:2 }}>{cleanStep(step)}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Notifications row */}
        {notifications.length > 0 && (
          <div style={{ display:"flex", gap:16, paddingTop:16, borderTop:"1px solid var(--border)" }}>
            <span style={{ fontSize:11, fontWeight:600, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.07em", paddingTop:2 }}>Notified</span>
            <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
              {notifications.includes("team_email")     && <Chip>📧 Team</Chip>}
              {notifications.includes("reporter_email") && <Chip>📧 Reporter</Chip>}
              {notifications.includes("slack")          && <Chip>💬 Slack</Chip>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Chip({ children }) {
  return (
    <span style={{ padding:"3px 10px", background:"var(--surface2)", border:"1px solid var(--border2)", borderRadius:6, fontSize:12, color:"var(--text2)" }}>
      {children}
    </span>
  );
}

// ── Runbook card ──────────────────────────────────────────────────────────────
function RunbookCard({ runbook, assigneeTeam, escalation }) {
  if (!runbook?.length) return null;
  return (
    <div style={{ background:"var(--surface)", border:"1px solid var(--border)", borderRadius:10, overflow:"hidden" }}>
      <div style={{ padding:"12px 20px", borderBottom:"1px solid var(--border)", display:"flex", alignItems:"center", justifyContent:"space-between" }}>
        <span style={{ fontSize:11, fontWeight:700, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.07em" }}>Runbook · {runbook.length} steps</span>
        <div style={{ display:"flex", gap:8, alignItems:"center" }}>
          {escalation && (
            <span style={{ fontSize:11, padding:"2px 8px", background:"rgba(239,68,68,.12)", border:"1px solid rgba(239,68,68,.3)", borderRadius:5, color:"#fca5a5", fontWeight:600 }}>🚨 Escalated</span>
          )}
          {assigneeTeam && (
            <span style={{ fontSize:11, padding:"2px 8px", background:"rgba(91,106,240,.1)", border:"1px solid rgba(91,106,240,.2)", borderRadius:5, color:"#a5b4fc" }}>{assigneeTeam}</span>
          )}
        </div>
      </div>
      <div style={{ padding:"12px 20px", display:"flex", flexDirection:"column", gap:10 }}>
        {runbook.map((step, i) => {
          const action  = typeof step === "string" ? step : step.action || "";
          const command = typeof step === "string" ? "" : step.command || "";
          const rationale = typeof step === "string" ? "" : step.rationale || "";
          return (
            <div key={i} style={{ display:"flex", gap:12, alignItems:"flex-start", paddingBottom:10, borderBottom: i < runbook.length-1 ? "1px solid var(--border)" : "none" }}>
              <span style={{ flexShrink:0, width:24, height:24, borderRadius:6, background:"rgba(91,106,240,.12)", border:"1px solid rgba(91,106,240,.25)", display:"flex", alignItems:"center", justifyContent:"center", fontSize:11, fontWeight:700, color:"#a5b4fc" }}>{i+1}</span>
              <div style={{ flex:1 }}>
                <div style={{ fontSize:13, fontWeight:500, color:"var(--text)", marginBottom:command ? 6 : 0 }}>{action}</div>
                {command && (
                  <code style={{ display:"block", background:"var(--surface2)", border:"1px solid var(--border2)", borderRadius:6, padding:"6px 10px", fontSize:11, fontFamily:"'JetBrains Mono',monospace", color:"#86efac", whiteSpace:"pre-wrap", wordBreak:"break-all", marginBottom:rationale ? 4 : 0 }}>
                    {command}
                  </code>
                )}
                {rationale && <div style={{ fontSize:11, color:"var(--text3)", marginTop:3 }}>{rationale}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Code files card ───────────────────────────────────────────────────────────
function CodeFilesCard({ files }) {
  if (!files?.length) return null;
  return (
    <div style={{ background:"var(--surface)", border:"1px solid var(--border)", borderRadius:10, overflow:"hidden" }}>
      <div style={{ padding:"10px 16px", borderBottom:"1px solid var(--border)" }}>
        <span style={{ fontSize:11, fontWeight:700, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.07em" }}>Relevant Files · {files.length}</span>
      </div>
      <div style={{ padding:"8px 0" }}>
        {files.map((f, i) => (
          <div key={i} style={{ padding:"7px 16px", display:"flex", alignItems:"center", gap:10, borderBottom: i < files.length-1 ? "1px solid var(--border)" : "none" }}>
            <span style={{ fontSize:12, opacity:.5 }}>📄</span>
            <code style={{ fontSize:12, color:"var(--text2)", fontFamily:"'JetBrains Mono',monospace" }}>{f}</code>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Incident info panel ───────────────────────────────────────────────────────
function IncidentInfo({ data, connected, pipelineDone, onBack }) {
  if (!data) return null;
  const title = data.title || data.raw_text?.split("\n")[0] || "";
  const desc  = data.raw_text?.includes("\n\n") ? data.raw_text.split("\n\n").slice(1).join("\n\n").trim() : data.description || "";

  return (
    <div style={{ background:"var(--surface)", border:"1px solid var(--border)", borderRadius:10, padding:"18px 20px" }}>
      <div style={{ display:"flex", alignItems:"flex-start", justifyContent:"space-between", gap:12, marginBottom:16 }}>
        <h2 style={{ fontSize:15, fontWeight:600, lineHeight:1.4, color:"var(--text)" }}>{title}</h2>
        <button onClick={onBack} style={{ flexShrink:0, padding:"4px 10px", background:"none", border:"1px solid var(--border2)", borderRadius:6, fontSize:12, color:"var(--text3)", transition:"all .15s" }}>← Back</button>
      </div>

      <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
        <Field label="ID"><span style={{ fontFamily:"monospace", fontSize:11, color:"var(--text3)" }}>{data.incident_id || data.id}</span></Field>
        {data.reporter_email && <Field label="Reporter"><span style={{ fontSize:12 }}>{data.reporter_email}</span></Field>}
        {data.created_at && <Field label="Submitted"><span style={{ fontSize:12 }}>{new Date(data.created_at).toLocaleString()}</span></Field>}
      </div>

      {desc && (
        <div style={{ marginTop:14, paddingTop:14, borderTop:"1px solid var(--border)" }}>
          <div style={{ fontSize:11, fontWeight:700, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.07em", marginBottom:6 }}>Description</div>
          <p style={{ fontSize:12, color:"var(--text3)", lineHeight:1.65, maxHeight:140, overflow:"hidden" }}>{desc}</p>
        </div>
      )}

      <div style={{ marginTop:14, paddingTop:12, borderTop:"1px solid var(--border)", display:"flex", alignItems:"center", gap:6 }}>
        <span style={{ width:7, height:7, borderRadius:"50%", background: pipelineDone ? "var(--green)" : connected ? "var(--green)" : "#fbbf24", display:"inline-block" }} />
        <span style={{ fontSize:11, color:"var(--text3)" }}>{pipelineDone ? "Completed" : connected ? "Live" : "Connecting…"}</span>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ display:"flex", gap:8, alignItems:"baseline" }}>
      <span style={{ fontSize:11, fontWeight:600, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.06em", minWidth:70, flexShrink:0 }}>{label}</span>
      <span style={{ color:"var(--text2)" }}>{children}</span>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function TriageView({ incidentId, onBack }) {
  const { messages, connected } = useWebSocket(incidentId);
  const [incidentData, setIncidentData] = useState(null);
  const [loading, setLoading]   = useState(true);
  const [agentState, setAgentState] = useState({});
  const [pipelineDone, setPipelineDone] = useState(false);
  const [summary, setSummary]   = useState(null);

  useEffect(() => {
    fetch(`/api/incidents/${incidentId}`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => {
        setIncidentData(d);
        setLoading(false);
        const pr = d.pipeline_result;
        if (!pr) return;
        const newState = {};
        if (pr.intake && Object.keys(pr.intake).length)
          newState.intake = { status:"done", result:{ title:pr.intake.title, affected_service:pr.intake.affected_service, error_type:pr.intake.error_type, information_sufficient:pr.intake.information_sufficient }};
        if (pr.code_analysis)
          newState.code_analysis = { status:"done", result:{ relevant_files:pr.code_analysis.relevant_files||[], summary:pr.code_analysis.analysis_summary, degraded:pr.code_analysis.degraded }};
        if (pr.dedup_result)
          newState.dedup = { status:"done", result:{ is_duplicate:pr.dedup_result.is_duplicate, highest_similarity:pr.dedup_result.highest_similarity, recommendation:pr.dedup_result.recommendation, linked_incident_id:pr.dedup_result.linked_incident_id }};
        if (pr.triage_verdict)
          newState.triage_synth = { status:"done", result:{ severity:pr.triage_verdict.severity, confidence:pr.triage_verdict.confidence, root_cause_hypothesis:pr.triage_verdict.root_cause_hypothesis, investigation_steps:pr.triage_verdict.investigation_steps, runbook:pr.triage_verdict.runbook||pr.runbook||[], suggested_assignee_team:pr.triage_verdict.suggested_assignee_team||pr.suggested_assignee_team||"sre-team", needs_human_review:pr.triage_verdict.needs_human_review }};
        if (pr.ticket_id)
          newState.ticket = { status:"done", result:{ ticket_id:pr.ticket_id, ticket_url:pr.ticket_url }};
        if (pr.notifications_sent)
          newState.notify = { status:"done", result:{ notifications_sent:pr.notifications_sent }};
        if (Object.keys(newState).length) {
          setAgentState(prev => ({ ...prev, ...newState }));
          setPipelineDone(true);
          setSummary(pr);
        }
      })
      .catch(() => setLoading(false));
  }, [incidentId]);

  useEffect(() => {
    if (!messages.length) return;
    const { phase, agent, data = {} } = messages[messages.length - 1];
    const id = agent === "run_code_analysis" ? "code_analysis" : agent === "escalate" ? "escalate" : agent;
    if (phase === "agent_started")
      setAgentState(p => ({ ...p, [id]:{ status:"running", result:null } }));
    else if (phase === "agent_completed")
      setAgentState(p => ({ ...p, [id]:{ status:"done", result:data } }));
    else if (phase === "pipeline_completed") { setPipelineDone(true); setSummary(data); }
    else if (phase === "pipeline_failed") setPipelineDone(true);
  }, [messages]);

  if (loading) return (
    <div style={{ display:"flex", alignItems:"center", justifyContent:"center", height:300, color:"var(--text3)", gap:10 }}>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <div style={{ width:20, height:20, border:"2px solid var(--border2)", borderTopColor:"var(--accent)", borderRadius:"50%", animation:"spin .6s linear infinite" }} />
      Loading…
    </div>
  );

  const verdict      = agentState.triage_synth?.result;
  const isDuplicate  = agentState.dedup?.result?.is_duplicate;
  const codeFiles    = agentState.code_analysis?.result?.relevant_files || [];
  const runbook      = verdict?.runbook || summary?.runbook || [];
  const assigneeTeam = verdict?.suggested_assignee_team || summary?.suggested_assignee_team || "";
  const escalation   = summary?.escalation_triggered || false;

  return (
    <div style={{ display:"grid", gridTemplateColumns:"300px 1fr", gap:20, alignItems:"start" }}>
      {/* Left column */}
      <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
        <IncidentInfo data={incidentData} connected={connected} pipelineDone={pipelineDone} onBack={onBack} />
        <PipelinePanel agentState={agentState} />
      </div>

      {/* Right column */}
      <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
        {pipelineDone && verdict?.severity && (
          <TriageCard verdict={verdict} summary={summary} isDuplicate={isDuplicate} />
        )}
        {!pipelineDone && (
          <div style={{ background:"var(--surface)", border:"1px solid var(--border)", borderRadius:10, padding:"40px 24px", textAlign:"center", color:"var(--text3)" }}>
            <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
            <div style={{ width:28, height:28, border:"2px solid var(--border2)", borderTopColor:"var(--accent)", borderRadius:"50%", animation:"spin .6s linear infinite", margin:"0 auto 16px" }} />
            <div style={{ fontSize:14, color:"var(--text2)" }}>Analyzing incident…</div>
            <div style={{ fontSize:12, marginTop:4 }}>Results will appear here as agents complete</div>
          </div>
        )}
        {pipelineDone && runbook.length > 0 && (
          <RunbookCard runbook={runbook} assigneeTeam={assigneeTeam} escalation={escalation} />
        )}
        <CodeFilesCard files={codeFiles} />
      </div>
    </div>
  );
}
