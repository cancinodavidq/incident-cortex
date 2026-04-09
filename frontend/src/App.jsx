import React, { useState } from "react";
import IncidentForm from "./components/IncidentForm";
import TriageView from "./components/TriageView";
import IncidentList from "./components/IncidentList";
import MetricsDashboard from "./components/MetricsDashboard";

const s = {
  shell: { display:"flex", flexDirection:"column", minHeight:"100vh" },
  header: { borderBottom:"1px solid var(--border)", background:"var(--surface)", padding:"0 32px", display:"flex", alignItems:"center", justifyContent:"space-between", height:56, flexShrink:0 },
  logo: { display:"flex", alignItems:"center", gap:10 },
  logoIcon: { width:28, height:28, background:"var(--accent)", borderRadius:6, display:"flex", alignItems:"center", justifyContent:"center", fontSize:14 },
  logoText: { fontWeight:700, fontSize:15, letterSpacing:"-0.02em" },
  logoSub: { fontSize:11, color:"var(--text3)", marginTop:1 },
  nav: { display:"flex", gap:2 },
  tab: { padding:"6px 14px", borderRadius:6, fontSize:13, fontWeight:500, background:"none", border:"none", color:"var(--text2)", transition:"all .15s" },
  tabActive: { background:"var(--surface2)", color:"var(--text)", border:"none" },
  main: { flex:1, padding:"32px", maxWidth:1100, width:"100%", margin:"0 auto" },
};

export default function App() {
  const [tab, setTab] = useState("submit");
  const [incidentId, setIncidentId] = useState(null);

  const go = (t) => { setTab(t); setIncidentId(null); };

  const handleSubmitted = (id) => { setIncidentId(id); setTab("triage"); };
  const handleSelect    = (id) => { setIncidentId(id); setTab("triage"); };

  return (
    <div style={s.shell}>
      <header style={s.header}>
        <div style={s.logo}>
          <div style={s.logoIcon}>⚡</div>
          <div>
            <div style={s.logoText}>Incident Cortex</div>
            <div style={s.logoSub}>SRE Triage Pipeline</div>
          </div>
        </div>
        <nav style={s.nav}>
          {[["submit","Submit"],["recent","Recent"],["metrics","Metrics"]].map(([id,label]) => (
            <button key={id} style={tab===id ? {...s.tab,...s.tabActive} : s.tab} onClick={() => go(id)}>{label}</button>
          ))}
        </nav>
      </header>

      <main style={s.main}>
        {tab === "submit"  && !incidentId && <IncidentForm onSubmitted={handleSubmitted} />}
        {tab === "triage"  && incidentId  && <TriageView incidentId={incidentId} onBack={() => go("recent")} />}
        {tab === "recent"  && !incidentId && <IncidentList onSelect={handleSelect} />}
        {tab === "metrics" && <MetricsDashboard />}
      </main>
    </div>
  );
}

