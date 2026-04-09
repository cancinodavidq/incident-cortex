import React, { useState, useEffect, useRef } from "react";
import { useWebSocket } from "../hooks/useWebSocket";

// ── Design tokens ─────────────────────────────────────────────────────────────
const SEV = {
  P1: { bg:"rgba(239,68,68,.1)",  border:"rgba(239,68,68,.35)",  badge:"#ef4444", badgeText:"#fff",    label:"Critical"  },
  P2: { bg:"rgba(249,115,22,.1)", border:"rgba(249,115,22,.35)", badge:"#f97316", badgeText:"#fff",    label:"High"      },
  P3: { bg:"rgba(234,179,8,.1)",  border:"rgba(234,179,8,.35)",  badge:"#eab308", badgeText:"#000",    label:"Medium"    },
  P4: { bg:"rgba(34,197,94,.1)",  border:"rgba(34,197,94,.35)",  badge:"#22c55e", badgeText:"#000",    label:"Low"       },
};

const TOOL_META = {
  intake:        { icon:"🔍", label:"parse_incident",     color:"#a5b4fc", skill:false },
  code_analysis: { icon:"💻", label:"search_codebase",    color:"#86efac", skill:false },
  dedup:         { icon:"🔁", label:"check_duplicates",   color:"#86efac", skill:false },
  metrics:       { icon:"📊", label:"query_metrics",      color:"#c4b5fd", skill:true  },
  triage_synth:  { icon:"⚙️", label:"synthesize_triage",  color:"#fcd34d", skill:false },
  escalate:      { icon:"🚨", label:"escalate_p1",        color:"#fca5a5", skill:false },
  ticket:        { icon:"🎫", label:"create_ticket",      color:"#a5b4fc", skill:false },
  notify:        { icon:"📣", label:"send_notifications", color:"#fdba74", skill:false },
};

// All tools in canonical pipeline order (for the "used / skipped" overview)
const ALL_TOOLS = ["intake","code_analysis","dedup","metrics","triage_synth","escalate","ticket","notify"];

function cleanStep(s) { return s.replace(/^\d+\.\d*\s*/, "").replace(/^[-•]\s*/, "").trim(); }

// ── Tool result snippet ───────────────────────────────────────────────────────
function ToolSnippet({ agent, data }) {
  if (!data) return null;
  const st = { fontSize:11, color:"var(--text3)", marginTop:3, lineHeight:1.5 };

  if (agent === "intake") {
    if (data.information_sufficient === false)
      return <span style={{...st, color:"#fcd34d"}}>⚠ needs clarification</span>;
    const parts = [data.affected_service, data.error_type].filter(Boolean);
    return <span style={st}>{parts.join(" · ") || "parsed"}</span>;
  }
  if (agent === "code_analysis") {
    const files = data.relevant_files || [];
    const n = files.length;
    if (data.degraded) return <span style={{...st, color:"#fcd34d"}}>degraded — no index yet</span>;
    return <span style={st}>{n ? `${n} file${n>1?"s":""} · ${files[0]?.split("/").pop() || ""}` : "no files found"}</span>;
  }
  if (agent === "dedup") {
    const sim = Math.round((data.highest_similarity||0)*100);
    return <span style={{...st, color: data.is_duplicate ? "#fcd34d" : "#86efac"}}>
      {data.is_duplicate ? `duplicate · ${sim}% match` : `new · ${sim}% max sim`}
    </span>;
  }
  if (agent === "metrics") {
    const anomaly = data.anomaly_detected;
    return (
      <span style={{ ...st, color: anomaly ? "#fca5a5" : "#86efac" }}>
        {data.service} · err {Math.round((data.error_rate||0)*100)}% · p95 {data.p95_latency_ms}ms
        {anomaly ? " · ⚠ anomaly" : " · ✓ normal"}
      </span>
    );
  }
  if (agent === "triage_synth") {
    if (!data.severity) return <span style={st}>skipped (duplicate)</span>;
    const sev = SEV[data.severity];
    return (
      <span style={{ display:"inline-flex", alignItems:"center", gap:5, marginTop:3 }}>
        <span style={{ background:sev?.badge, color:sev?.badgeText, padding:"1px 5px", borderRadius:4, fontSize:10, fontWeight:700 }}>{data.severity}</span>
        <span style={st}>{Math.round((data.confidence||0)*100)}% conf · {data.runbook_steps||0} runbook steps</span>
      </span>
    );
  }
  if (agent === "escalate")
    return <span style={{...st, color:"#fca5a5"}}>oncall paged · {data.team_paged || "sre-team"}</span>;
  if (agent === "ticket")
    return <span style={{...st, color:"#a5b4fc", fontFamily:"monospace"}}>{data.ticket_id || "MANUAL-REQUIRED"}</span>;
  if (agent === "notify") {
    const sent = (data.notifications_sent||[]).map(n => n.replace("_email"," ✉").replace("slack","💬 slack"));
    return <span style={st}>{sent.join(" · ") || "none"}</span>;
  }
  return null;
}

// ── Spinner ───────────────────────────────────────────────────────────────────
function Spinner({ size=10 }) {
  return (
    <>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <span style={{ width:size, height:size, border:`1.5px solid rgba(91,106,240,.3)`, borderTopColor:"var(--accent)", borderRadius:"50%", display:"inline-block", animation:"spin .6s linear infinite", flexShrink:0 }} />
    </>
  );
}

// ── Tool overview row (used vs skipped) ──────────────────────────────────────
function ToolOverview({ toolLog, pipelineDone }) {
  const usedAgents = new Set(toolLog.filter(e => e.status === "done").map(e => e.agent));
  const runningAgents = new Set(toolLog.filter(e => e.status === "running").map(e => e.agent));

  return (
    <div style={{ padding:"10px 14px", borderBottom:"1px solid var(--border)", display:"flex", flexWrap:"wrap", gap:6 }}>
      {ALL_TOOLS.map(agentId => {
        const meta = TOOL_META[agentId];
        const used    = usedAgents.has(agentId);
        const running = runningAgents.has(agentId);
        const pending = !used && !running;

        let bg, border, textColor, dotColor;
        if (running) {
          bg = "rgba(91,106,240,.12)"; border = "rgba(91,106,240,.3)";
          textColor = "#a5b4fc"; dotColor = "var(--accent)";
        } else if (used) {
          bg = "rgba(34,197,94,.07)"; border = "rgba(34,197,94,.25)";
          textColor = meta.color; dotColor = "#22c55e";
        } else {
          bg = "transparent"; border = "var(--border)";
          textColor = "var(--text3)"; dotColor = "var(--border2)";
        }

        return (
          <div key={agentId} style={{
            display:"inline-flex", alignItems:"center", gap:5,
            padding:"3px 8px", borderRadius:5,
            background:bg, border:`1px solid ${border}`,
            opacity: pending && pipelineDone ? 0.45 : 1,
            transition:"all .3s",
          }}>
            {running
              ? <Spinner size={8} />
              : <span style={{ width:6, height:6, borderRadius:"50%", background:dotColor, display:"inline-block", flexShrink:0 }} />
            }
            <span style={{ fontSize:10, fontFamily:"'JetBrains Mono',monospace", color:textColor, whiteSpace:"nowrap" }}>
              {meta.label}
            </span>
            {meta.skill && (
              <span style={{ fontSize:8, padding:"0 3px", background:"rgba(196,181,253,.15)", border:"1px solid rgba(196,181,253,.3)", borderRadius:2, color:"#c4b5fd", fontWeight:700, letterSpacing:"0.04em" }}>SKILL</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── ReAct log panel ───────────────────────────────────────────────────────────
function ReactLog({ toolLog, reasoningLog, pipelineDone, totalIterations }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    if (bottomRef.current) bottomRef.current.scrollIntoView({ behavior:"smooth" });
  }, [toolLog, reasoningLog]);

  // Group tools by turn
  const turnMap = {};
  for (const entry of toolLog) {
    const t = entry.turn || 1;
    if (!turnMap[t]) turnMap[t] = [];
    turnMap[t].push(entry);
  }
  // Build reasoning index by turn
  const reasoningByTurn = {};
  for (const r of reasoningLog) reasoningByTurn[r.turn] = r.text;

  // All turns that have either tools or reasoning
  const allTurnNums = new Set([
    ...Object.keys(turnMap).map(Number),
    ...reasoningLog.map(r => r.turn),
  ]);
  const turns = [...allTurnNums].sort((a,b) => a-b)
    .map(t => ({ turn:t, tools: turnMap[t] || [], reasoning: reasoningByTurn[t] || null }));

  const maxTurn = turns.length ? Math.max(...turns.map(t=>t.turn)) : 0;
  const hasRunning = toolLog.some(e => e.status === "running");

  return (
    <div style={{ background:"var(--surface)", border:"1px solid var(--border)", borderRadius:10, overflow:"hidden" }}>
      {/* Header */}
      <div style={{ padding:"10px 14px", borderBottom:"1px solid var(--border)", display:"flex", alignItems:"center", justifyContent:"space-between" }}>
        <div style={{ display:"flex", alignItems:"center", gap:8 }}>
          <span style={{ fontSize:11, fontWeight:600, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.07em" }}>ReAct Loop</span>
          <span style={{ fontSize:10, padding:"1px 6px", background:"rgba(91,106,240,.12)", border:"1px solid rgba(91,106,240,.25)", borderRadius:4, color:"#a5b4fc", fontFamily:"monospace" }}>claude-sonnet-4-6</span>
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:8 }}>
          {hasRunning && <Spinner size={9} />}
          {(pipelineDone && totalIterations) ? (
            <span style={{ fontSize:11, color:"var(--text3)", fontFamily:"monospace" }}>{totalIterations} turns</span>
          ) : maxTurn > 0 ? (
            <span style={{ fontSize:11, color:"var(--text3)", fontFamily:"monospace" }}>turn {maxTurn}</span>
          ) : null}
          {pipelineDone && (
            <span style={{ width:7, height:7, borderRadius:"50%", background:"var(--green)", display:"inline-block" }} />
          )}
        </div>
      </div>

      {/* Tool overview: used vs skipped */}
      <ToolOverview toolLog={toolLog} pipelineDone={pipelineDone} />

      {/* Log body */}
      <div style={{ padding:"8px 0", maxHeight:420, overflowY:"auto", fontSize:12 }}>
        {turns.length === 0 && (
          <div style={{ padding:"16px 14px", color:"var(--text3)", display:"flex", alignItems:"center", gap:8 }}>
            <Spinner size={10} />
            <span>Waiting for Claude…</span>
          </div>
        )}

        {turns.map(({ turn, tools, reasoning }) => {
          const isParallel = tools.length > 1;
          const allDone    = tools.every(t => t.status === "done");
          const anyRunning = tools.some(t => t.status === "running");

          return (
            <div key={turn} style={{ borderBottom:"1px solid rgba(37,40,54,.6)", paddingBottom:8, marginBottom:2 }}>
              {/* Turn header */}
              <div style={{ display:"flex", alignItems:"center", gap:8, padding:"4px 14px 2px" }}>
                <span style={{ fontSize:10, color:"var(--text3)", fontFamily:"monospace", minWidth:40 }}>
                  turn {turn}
                </span>
                {isParallel && (
                  <span style={{ fontSize:9, padding:"1px 5px", background:"rgba(91,106,240,.1)", border:"1px solid rgba(91,106,240,.2)", borderRadius:3, color:"#a5b4fc", fontWeight:600, letterSpacing:"0.05em", textTransform:"uppercase" }}>parallel</span>
                )}
                {anyRunning && <Spinner size={8} />}
                {allDone && !anyRunning && (
                  <span style={{ fontSize:9, color:"#86efac", opacity:.7 }}>✓</span>
                )}
              </div>

              {/* Claude's reasoning for this turn */}
              {reasoning && (
                <div style={{ margin:"4px 14px 6px 32px", padding:"6px 10px", background:"rgba(91,106,240,.05)", borderLeft:"2px solid rgba(91,106,240,.25)", borderRadius:"0 4px 4px 0" }}>
                  <span style={{ fontSize:10, fontStyle:"italic", color:"var(--text3)", lineHeight:1.55, display:"block" }}>
                    {reasoning}
                  </span>
                </div>
              )}

              {/* Tool rows */}
              {tools.map((entry, i) => {
                const meta = TOOL_META[entry.agent] || { icon:"🔧", label:entry.agent, color:"var(--text3)" };
                const isRunning = entry.status === "running";
                const isDone    = entry.status === "done";

                return (
                  <div key={i} style={{
                    display:"flex", alignItems:"flex-start", gap:10, padding:"5px 14px 3px 32px",
                    background: isRunning ? "rgba(91,106,240,.06)" : "transparent",
                    transition:"background .2s",
                  }}>
                    {/* Status indicator */}
                    <div style={{ flexShrink:0, marginTop:1 }}>
                      {isRunning ? <Spinner size={10} /> : (
                        <span style={{ width:10, height:10, borderRadius:"50%", background: isDone ? "rgba(34,197,94,.25)" : "var(--surface2)", border:`1px solid ${isDone ? "rgba(34,197,94,.5)" : "var(--border2)"}`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:7, color:"var(--green)" }}>
                          {isDone ? "✓" : ""}
                        </span>
                      )}
                    </div>

                    {/* Tool name + result */}
                    <div style={{ flex:1, minWidth:0 }}>
                      <div style={{ display:"flex", alignItems:"center", gap:6 }}>
                        <span style={{ fontSize:12 }}>{meta.icon}</span>
                        <code style={{ fontSize:11, color: isRunning ? "var(--text)" : isDone ? meta.color : "var(--text3)", fontFamily:"'JetBrains Mono',monospace", fontWeight: isRunning ? 600 : 400 }}>
                          {meta.label}
                        </code>
                        {isRunning && <span style={{ fontSize:10, color:"var(--accent)", opacity:.7 }}>{entry.message || "running…"}</span>}
                      </div>
                      {isDone && <ToolSnippet agent={entry.agent} data={entry.result} />}
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })}

        <div ref={bottomRef} />
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

      <div style={{ padding:"20px" }}>
        {verdict.root_cause_hypothesis && (
          <div style={{ marginBottom:24 }}>
            <div style={{ fontSize:11, fontWeight:700, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.08em", marginBottom:8 }}>Root Cause</div>
            <p style={{ fontSize:14, color:"var(--text)", lineHeight:1.65 }}>{verdict.root_cause_hypothesis}</p>
          </div>
        )}

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
function IncidentInfo({ data, pipelineDone, totalIterations, onBack }) {
  if (!data) return null;
  const title = data.title || data.raw_text?.split("\n")[0] || "";
  const desc  = data.raw_text?.includes("\n\n") ? data.raw_text.split("\n\n").slice(1).join("\n\n").trim() : data.description || "";

  return (
    <div style={{ background:"var(--surface)", border:"1px solid var(--border)", borderRadius:10, padding:"18px 20px" }}>
      <div style={{ display:"flex", alignItems:"flex-start", justifyContent:"space-between", gap:12, marginBottom:16 }}>
        <h2 style={{ fontSize:15, fontWeight:600, lineHeight:1.4, color:"var(--text)" }}>{title}</h2>
        <button onClick={onBack} style={{ flexShrink:0, padding:"4px 10px", background:"none", border:"1px solid var(--border2)", borderRadius:6, fontSize:12, color:"var(--text3)" }}>← Back</button>
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

      <div style={{ marginTop:14, paddingTop:12, borderTop:"1px solid var(--border)", display:"flex", alignItems:"center", justifyContent:"space-between" }}>
        <div style={{ display:"flex", alignItems:"center", gap:6 }}>
          <span style={{ width:7, height:7, borderRadius:"50%", background: pipelineDone ? "var(--green)" : "#fbbf24", display:"inline-block" }} />
          <span style={{ fontSize:11, color:"var(--text3)" }}>{pipelineDone ? "Completed" : "Processing…"}</span>
        </div>
        {totalIterations && (
          <span style={{ fontSize:10, color:"var(--text3)", fontFamily:"monospace" }}>{totalIterations} turns</span>
        )}
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

// ── Tool log reconstruction from pipeline_result ──────────────────────────────
function buildToolLogFromPR(pr) {
  const log = [];
  if (!pr) return log;
  if (pr.intake && Object.keys(pr.intake).length)
    log.push({ turn:1, agent:"intake",        status:"done", result:{ ...pr.intake } });
  if (pr.code_analysis)
    log.push({ turn:2, agent:"code_analysis", status:"done", result:{ relevant_files:pr.code_analysis.relevant_files||[], degraded:pr.code_analysis.degraded, analysis_summary:pr.code_analysis.analysis_summary } });
  if (pr.dedup_result)
    log.push({ turn:2, agent:"dedup",         status:"done", result:{ ...pr.dedup_result } });
  if (pr.metrics_result && Object.keys(pr.metrics_result).length)
    log.push({ turn:2, agent:"metrics",       status:"done", result:{ ...pr.metrics_result } });
  if (pr.triage_verdict || pr.severity) {
    const v = pr.triage_verdict || {};
    log.push({ turn:3, agent:"triage_synth",  status:"done", result:{ severity:v.severity||pr.severity, confidence:v.confidence||pr.confidence, runbook_steps:(v.runbook||pr.runbook||[]).length } });
  }
  let t = 4;
  if (pr.escalation_triggered)
    log.push({ turn:t++, agent:"escalate", status:"done", result:{ escalated:true, team_paged:pr.suggested_assignee_team||"sre-team" } });
  if (pr.ticket_id && !pr.is_duplicate)
    log.push({ turn:t++, agent:"ticket",   status:"done", result:{ ticket_id:pr.ticket_id } });
  if (pr.notifications_sent?.length)
    log.push({ turn:t,   agent:"notify",   status:"done", result:{ notifications_sent:pr.notifications_sent } });
  return log;
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function TriageView({ incidentId, onBack }) {
  const { messages } = useWebSocket(incidentId);
  const [incidentData,  setIncidentData]  = useState(null);
  const [loading,       setLoading]       = useState(true);
  const [toolLog,       setToolLog]       = useState([]);
  const [reasoningLog,  setReasoningLog]  = useState([]);
  const [agentState,    setAgentState]    = useState({});
  const [pipelineDone,  setPipelineDone]  = useState(false);
  const [summary,       setSummary]       = useState(null);

  // ── Load incident + reconstruct from pipeline_result ─────────────────────
  useEffect(() => {
    fetch(`/api/incidents/${incidentId}`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => {
        setIncidentData(d);
        setLoading(false);
        const pr = d.pipeline_result;
        if (!pr) return;

        // Reconstruct agent state for TriageCard etc.
        const ns = {};
        if (pr.intake)
          ns.intake = { status:"done", result:pr.intake };
        if (pr.code_analysis)
          ns.code_analysis = { status:"done", result:{ relevant_files:pr.code_analysis.relevant_files||[], degraded:pr.code_analysis.degraded }};
        if (pr.dedup_result)
          ns.dedup = { status:"done", result:pr.dedup_result };
        if (pr.triage_verdict || pr.severity) {
          const v = pr.triage_verdict || {};
          ns.triage_synth = { status:"done", result:{ severity:v.severity||pr.severity, confidence:v.confidence||pr.confidence, root_cause_hypothesis:v.root_cause_hypothesis||pr.root_cause_hypothesis, investigation_steps:v.investigation_steps||pr.investigation_steps||[], runbook:v.runbook||pr.runbook||[], suggested_assignee_team:v.suggested_assignee_team||pr.suggested_assignee_team||"sre-team", needs_human_review:v.needs_human_review||pr.needs_human_review }};
        }
        if (pr.metrics_result && Object.keys(pr.metrics_result).length)
          ns.metrics = { status:"done", result:{ ...pr.metrics_result } };
        if (pr.ticket_id)
          ns.ticket = { status:"done", result:{ ticket_id:pr.ticket_id } };
        if (pr.notifications_sent)
          ns.notify = { status:"done", result:{ notifications_sent:pr.notifications_sent }};

        setAgentState(ns);
        setSummary(pr);
        setPipelineDone(true);
        setToolLog(buildToolLogFromPR(pr));
      })
      .catch(() => setLoading(false));
  }, [incidentId]);

  // ── Live WS messages → update toolLog + agentState ───────────────────────
  useEffect(() => {
    if (!messages.length) return;
    const msg = messages[messages.length - 1];
    const { phase, agent, data = {} } = msg;
    const turn = data.turn || 1;

    if (phase === "agent_started") {
      setToolLog(prev => {
        const exists = prev.find(e => e.turn === turn && e.agent === agent);
        if (exists) return prev.map(e => e.turn===turn && e.agent===agent ? {...e, status:"running", message:data.message} : e);
        return [...prev, { turn, agent, status:"running", message:data.message, result:null, parallel:data.parallel }];
      });
      setAgentState(p => ({ ...p, [agent]:{ status:"running", result:null } }));
    }
    else if (phase === "agent_completed") {
      setToolLog(prev => prev.map(e =>
        e.turn === turn && e.agent === agent ? { ...e, status:"done", result:data } : e
      ));
      setAgentState(p => ({ ...p, [agent]:{ status:"done", result:data } }));
    }
    else if (phase === "agent_reasoning") {
      setReasoningLog(prev => {
        const exists = prev.find(r => r.turn === data.turn);
        if (exists) return prev;
        return [...prev, { turn: data.turn, text: data.text, tools_called: data.tools_called || [] }];
      });
    }
    else if (phase === "pipeline_completed") {
      setPipelineDone(true);
      setSummary(data);
      // Backfill any missing entries from summary
      setToolLog(prev => prev.length > 0 ? prev : buildToolLogFromPR(data));
    }
    else if (phase === "pipeline_failed") {
      setPipelineDone(true);
    }
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
  const totalIters   = summary?.iterations || null;

  return (
    <div style={{ display:"grid", gridTemplateColumns:"320px 1fr", gap:20, alignItems:"start" }}>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>

      {/* Left column */}
      <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
        <IncidentInfo
          data={incidentData}
          pipelineDone={pipelineDone}
          totalIterations={totalIters}
          onBack={onBack}
        />
        <ReactLog
          toolLog={toolLog}
          reasoningLog={reasoningLog}
          pipelineDone={pipelineDone}
          totalIterations={totalIters}
        />
      </div>

      {/* Right column */}
      <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
        {pipelineDone && verdict?.severity && (
          <TriageCard verdict={verdict} summary={summary} isDuplicate={isDuplicate} />
        )}
        {!pipelineDone && (
          <div style={{ background:"var(--surface)", border:"1px solid var(--border)", borderRadius:10, padding:"40px 24px", textAlign:"center", color:"var(--text3)" }}>
            <div style={{ width:28, height:28, border:"2px solid var(--border2)", borderTopColor:"var(--accent)", borderRadius:"50%", animation:"spin .6s linear infinite", margin:"0 auto 16px" }} />
            <div style={{ fontSize:14, color:"var(--text2)" }}>Claude is reasoning…</div>
            <div style={{ fontSize:12, marginTop:4 }}>Tool calls will appear on the left as they execute</div>
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
