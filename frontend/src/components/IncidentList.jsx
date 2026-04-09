import React, { useState, useEffect } from "react";

const SEV_STYLE = {
  P1: { background:"rgba(239,68,68,.15)",  color:"#fca5a5", border:"1px solid rgba(239,68,68,.3)" },
  P2: { background:"rgba(249,115,22,.15)", color:"#fdba74", border:"1px solid rgba(249,115,22,.3)" },
  P3: { background:"rgba(234,179,8,.15)",  color:"#fde047", border:"1px solid rgba(234,179,8,.3)" },
  P4: { background:"rgba(34,197,94,.15)",  color:"#86efac", border:"1px solid rgba(34,197,94,.3)" },
};

const s = {
  header: { display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:20 },
  title:  { fontSize:20, fontWeight:700, letterSpacing:"-0.02em" },
  sub:    { fontSize:13, color:"var(--text2)", marginTop:2 },
  btn:    { padding:"7px 14px", background:"var(--surface2)", border:"1px solid var(--border2)", borderRadius:7, color:"var(--text2)", fontSize:13, fontWeight:500, transition:"all .15s" },
  card:   { background:"var(--surface)", border:"1px solid var(--border)", borderRadius:10, overflow:"hidden" },
  table:  { width:"100%", borderCollapse:"collapse" },
  th:     { padding:"10px 16px", textAlign:"left", fontSize:11, fontWeight:600, color:"var(--text3)", textTransform:"uppercase", letterSpacing:"0.07em", borderBottom:"1px solid var(--border)" },
  td:     { padding:"13px 16px", borderBottom:"1px solid var(--border)", verticalAlign:"middle" },
  trHover:{ cursor:"pointer" },
  badge:  { display:"inline-block", padding:"2px 8px", borderRadius:5, fontSize:11, fontWeight:700, letterSpacing:"0.04em" },
  phase:  { display:"inline-block", padding:"2px 8px", borderRadius:5, fontSize:11, fontWeight:500 },
  mono:   { fontFamily:"'JetBrains Mono',monospace", fontSize:11, color:"var(--text3)" },
  empty:  { padding:"56px 24px", textAlign:"center", color:"var(--text3)" },
  footer: { padding:"12px 16px", borderTop:"1px solid var(--border)", display:"flex", alignItems:"center", justifyContent:"space-between" },
  count:  { fontSize:12, color:"var(--text3)" },
};

const PHASE_STYLE = {
  completed: { background:"rgba(34,197,94,.12)",  color:"#86efac" },
  submitted: { background:"rgba(139,144,168,.1)", color:"var(--text2)" },
  default:   { background:"rgba(91,106,240,.12)", color:"#a5b4fc" },
};

export default function IncidentList({ onSelect }) {
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);

  const load = async () => {
    try {
      const r = await fetch("/api/incidents");
      if (!r.ok) throw new Error("Failed to load");
      const d = await r.json();
      setIncidents(d.incidents || []);
      setLoading(false);
    } catch(e) {
      setError(e.message);
      setLoading(false);
    }
  };

  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, []);

  if (loading) return (
    <div style={{ ...s.empty, color:"var(--text2)" }}>
      <div style={{ width:28, height:28, border:"2px solid var(--border2)", borderTopColor:"var(--accent)", borderRadius:"50%", animation:"spin .6s linear infinite", margin:"0 auto 12px" }} />
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      Loading incidents…
    </div>
  );

  if (error) return (
    <div style={{ ...s.empty }}>
      <div style={{ color:"var(--red)", marginBottom:12 }}>Failed to load incidents</div>
      <button style={s.btn} onClick={load}>Retry</button>
    </div>
  );

  return (
    <div>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}} tr.inc-row:hover td{background:var(--surface2)}`}</style>
      <div style={s.header}>
        <div>
          <div style={s.title}>Incidents</div>
          <div style={s.sub}>{incidents.length} total</div>
        </div>
        <button style={s.btn} onClick={load}>↻ Refresh</button>
      </div>

      <div style={s.card}>
        {incidents.length === 0 ? (
          <div style={s.empty}>
            <div style={{ fontSize:28, marginBottom:10 }}>📭</div>
            <div>No incidents yet</div>
          </div>
        ) : (
          <table style={s.table}>
            <thead>
              <tr>
                {["ID","Title","Severity","Phase","Ticket","Time"].map(h => (
                  <th key={h} style={s.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {incidents.map(inc => {
                const phaseStyle = PHASE_STYLE[inc.phase] || PHASE_STYLE.default;
                const sevStyle   = SEV_STYLE[inc.severity];
                return (
                  <tr key={inc.incident_id} className="inc-row" style={s.trHover} onClick={() => onSelect(inc.incident_id)}>
                    <td style={s.td}>
                      <span style={s.mono}>{(inc.incident_id||"").substring(0,8)}…</span>
                    </td>
                    <td style={{ ...s.td, maxWidth:300 }}>
                      <div style={{ fontSize:13, fontWeight:500, color:"var(--text)", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
                        {inc.title || inc.raw_text?.split("\n")[0] || "—"}
                      </div>
                      {inc.reporter_email && (
                        <div style={{ fontSize:11, color:"var(--text3)", marginTop:2 }}>{inc.reporter_email}</div>
                      )}
                    </td>
                    <td style={s.td}>
                      {sevStyle ? (
                        <span style={{ ...s.badge, ...sevStyle }}>{inc.severity}</span>
                      ) : (
                        <span style={{ color:"var(--text3)", fontSize:12 }}>—</span>
                      )}
                    </td>
                    <td style={s.td}>
                      <span style={{ ...s.phase, ...phaseStyle }}>{inc.phase || "—"}</span>
                    </td>
                    <td style={s.td}>
                      {inc.ticket_id ? (
                        <a
                          href={`http://localhost:8081/browse/${inc.ticket_id}`}
                          target="_blank" rel="noopener noreferrer"
                          style={{ fontFamily:"monospace", fontSize:12, color:"var(--accent)" }}
                          onClick={e => e.stopPropagation()}
                        >
                          {inc.ticket_id}
                        </a>
                      ) : <span style={{ color:"var(--text3)", fontSize:12 }}>—</span>}
                    </td>
                    <td style={s.td}>
                      <span style={{ fontSize:12, color:"var(--text3)" }}>
                        {new Date(inc.created_at).toLocaleString(undefined, { month:"short", day:"numeric", hour:"2-digit", minute:"2-digit" })}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
