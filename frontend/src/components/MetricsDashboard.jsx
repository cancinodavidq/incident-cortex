import React, { useState, useEffect } from "react";

const s = {
  grid2: { display:"grid", gridTemplateColumns:"1fr 1fr", gap:16 },
  grid3: { display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:16 },
  card:  { background:"var(--surface)", border:"1px solid var(--border)", borderRadius:10, padding:"20px 22px" },
  label: { fontSize:11, fontWeight:600, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.07em", marginBottom:6 },
  big:   { fontSize:36, fontWeight:700, letterSpacing:"-0.03em", color:"var(--text)", lineHeight:1 },
  sub:   { fontSize:12, color:"var(--text3)", marginTop:4 },
  row:   { display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:10 },
  bar:   { height:8, borderRadius:4, background:"var(--surface2)", overflow:"hidden", flex:1, margin:"0 12px" },
};

const SEV_COLOR = { P1:"#ef4444", P2:"#f97316", P3:"#eab308", P4:"#22c55e" };
const SEV_BG    = { P1:"rgba(239,68,68,.12)", P2:"rgba(249,115,22,.12)", P3:"rgba(234,179,8,.12)", P4:"rgba(34,197,94,.12)" };

function StatCard({ label, value, sub, accent }) {
  return (
    <div style={s.card}>
      <div style={s.label}>{label}</div>
      <div style={{ ...s.big, color: accent || "var(--text)" }}>{value}</div>
      {sub && <div style={s.sub}>{sub}</div>}
    </div>
  );
}

function SeverityBar({ dist }) {
  const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1;
  const order = ["P1","P2","P3","P4"];
  return (
    <div style={s.card}>
      <div style={s.label}>Severity Distribution</div>
      <div style={{ display:"flex", height:16, borderRadius:6, overflow:"hidden", marginBottom:14, gap:1 }}>
        {order.map(p => {
          const pct = ((dist[p] || 0) / total) * 100;
          return pct > 0 ? (
            <div key={p} title={`${p}: ${dist[p]} (${pct.toFixed(0)}%)`}
              style={{ width:`${pct}%`, background:SEV_COLOR[p], transition:"width .4s" }} />
          ) : null;
        })}
      </div>
      <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
        {order.map(p => {
          const count = dist[p] || 0;
          const pct = (count / total) * 100;
          return (
            <div key={p} style={{ display:"flex", alignItems:"center", gap:10 }}>
              <span style={{ width:28, padding:"1px 6px", borderRadius:4, background:SEV_BG[p], color:SEV_COLOR[p], fontSize:11, fontWeight:700, textAlign:"center", flexShrink:0 }}>{p}</span>
              <div style={{ flex:1, height:6, borderRadius:3, background:"var(--surface2)", overflow:"hidden" }}>
                <div style={{ height:"100%", width:`${pct}%`, background:SEV_COLOR[p], borderRadius:3, transition:"width .4s" }} />
              </div>
              <span style={{ fontSize:12, color:"var(--text3)", minWidth:28, textAlign:"right" }}>{count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PipelineHealth({ p50, p95, dedup, review }) {
  const metrics = [
    { label:"P50 Triage Time", value: p50 < 60 ? `${p50.toFixed(0)}s` : `${(p50/60).toFixed(1)}m`, note:"median", color:"var(--green)" },
    { label:"P95 Triage Time", value: p95 < 60 ? `${p95.toFixed(0)}s` : `${(p95/60).toFixed(1)}m`, note:"95th percentile", color:"#a5b4fc" },
    { label:"Dedup Rate",       value: `${(dedup*100).toFixed(0)}%`, note:"auto-linked duplicates", color:"#fdba74" },
    { label:"Human Review Rate",value: `${(review*100).toFixed(0)}%`, note:"flagged for review", color:"#fcd34d" },
  ];
  return (
    <div style={s.card}>
      <div style={s.label}>Pipeline Health</div>
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:16, marginTop:8 }}>
        {metrics.map(m => (
          <div key={m.label} style={{ background:"var(--surface2)", border:"1px solid var(--border)", borderRadius:8, padding:"12px 14px" }}>
            <div style={{ fontSize:11, color:"var(--text3)", marginBottom:4 }}>{m.label}</div>
            <div style={{ fontSize:22, fontWeight:700, color:m.color, letterSpacing:"-0.02em" }}>{m.value}</div>
            <div style={{ fontSize:11, color:"var(--text3)", marginTop:2 }}>{m.note}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AgentPipeline() {
  const nodes = [
    { id:"intake",       label:"Intake",        desc:"Parse & validate" },
    { id:"code+dedup",   label:"Code + Dedup",  desc:"Parallel analysis", parallel:true },
    { id:"triage",       label:"Triage Synth",  desc:"Severity + runbook" },
    { id:"escalate",     label:"P1 Escalate",   desc:"Fast-path if critical", branch:true },
    { id:"ticket",       label:"Ticket",        desc:"Jira creation" },
    { id:"notify",       label:"Notify",        desc:"Email + Slack" },
  ];
  return (
    <div style={s.card}>
      <div style={s.label}>Agent Pipeline</div>
      <div style={{ display:"flex", alignItems:"center", gap:0, marginTop:12, flexWrap:"wrap", rowGap:8 }}>
        {nodes.map((n, i) => (
          <React.Fragment key={n.id}>
            <div style={{
              padding:"8px 12px",
              borderRadius:8,
              background: n.parallel ? "rgba(91,106,240,.12)" : n.branch ? "rgba(239,68,68,.1)" : "var(--surface2)",
              border: `1px solid ${n.parallel ? "rgba(91,106,240,.3)" : n.branch ? "rgba(239,68,68,.25)" : "var(--border2)"}`,
              minWidth:90, textAlign:"center",
            }}>
              <div style={{ fontSize:12, fontWeight:600, color: n.branch ? "#fca5a5" : "var(--text)" }}>{n.label}</div>
              <div style={{ fontSize:10, color:"var(--text3)", marginTop:2 }}>{n.desc}</div>
              {n.parallel && <div style={{ fontSize:9, color:"#a5b4fc", marginTop:2, fontWeight:600 }}>PARALLEL</div>}
              {n.branch && <div style={{ fontSize:9, color:"#fca5a5", marginTop:2, fontWeight:600 }}>P1 ONLY</div>}
            </div>
            {i < nodes.length - 1 && (
              <div style={{ fontSize:14, color:"var(--text3)", padding:"0 4px" }}>→</div>
            )}
          </React.Fragment>
        ))}
      </div>
      <div style={{ marginTop:12, fontSize:11, color:"var(--text3)", borderTop:"1px solid var(--border)", paddingTop:10 }}>
        Duplicates (similarity ≥ 85%) skip triage + ticket → routed directly to notify
      </div>
    </div>
  );
}

export default function MetricsDashboard() {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  const load = async () => {
    try {
      const r = await fetch("/api/metrics");
      if (!r.ok) throw new Error("Failed");
      const d = await r.json();
      setMetrics(d);
      setLastRefresh(new Date());
      setLoading(false);
    } catch(e) {
      setError(e.message);
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading) return (
    <div style={{ display:"flex", alignItems:"center", justifyContent:"center", height:300, gap:10, color:"var(--text3)" }}>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <div style={{ width:18, height:18, border:"2px solid var(--border2)", borderTopColor:"var(--accent)", borderRadius:"50%", animation:"spin .6s linear infinite" }} />
      Loading metrics…
    </div>
  );

  if (error) return (
    <div style={{ textAlign:"center", padding:"56px 0", color:"var(--text3)" }}>
      <div style={{ color:"var(--red)", marginBottom:12 }}>Failed to load metrics</div>
      <button onClick={load} style={{ padding:"6px 14px", background:"var(--surface2)", border:"1px solid var(--border2)", borderRadius:6, color:"var(--text2)", fontSize:13 }}>Retry</button>
    </div>
  );

  const { total_incidents, p50_triage_time_seconds, p95_triage_time_seconds, dedup_rate, severity_distribution, needs_human_review_rate } = metrics;
  const dist = severity_distribution || {};

  return (
    <div>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:24 }}>
        <div>
          <div style={{ fontSize:20, fontWeight:700, letterSpacing:"-0.02em" }}>Metrics</div>
          <div style={{ fontSize:13, color:"var(--text3)", marginTop:2 }}>Pipeline observability & incident trends</div>
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:10 }}>
          {lastRefresh && <span style={{ fontSize:11, color:"var(--text3)" }}>Updated {lastRefresh.toLocaleTimeString()}</span>}
          <button onClick={load} style={{ padding:"6px 12px", background:"var(--surface2)", border:"1px solid var(--border2)", borderRadius:6, color:"var(--text2)", fontSize:12, fontWeight:500 }}>↻ Refresh</button>
        </div>
      </div>

      {/* Top stats */}
      <div style={{ ...s.grid3, marginBottom:16 }}>
        <StatCard label="Total Incidents" value={total_incidents} sub="all time" />
        <StatCard
          label="P1 Critical"
          value={dist.P1 || 0}
          sub="immediate escalation"
          accent={(dist.P1 || 0) > 0 ? "#ef4444" : undefined}
        />
        <StatCard
          label="Auto-Resolved"
          value={`${Math.round((1 - (needs_human_review_rate || 0)) * 100)}%`}
          sub="no human review needed"
          accent="var(--green)"
        />
      </div>

      {/* Middle row */}
      <div style={{ ...s.grid2, marginBottom:16 }}>
        <SeverityBar dist={dist} />
        <PipelineHealth
          p50={p50_triage_time_seconds}
          p95={p95_triage_time_seconds}
          dedup={dedup_rate}
          review={needs_human_review_rate}
        />
      </div>

      {/* Pipeline diagram */}
      <AgentPipeline />
    </div>
  );
}
