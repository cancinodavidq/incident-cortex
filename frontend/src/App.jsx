import React, { useState } from "react";
import IncidentForm from "./components/IncidentForm";
import TriageView from "./components/TriageView";
import IncidentList from "./components/IncidentList";
import MetricsDashboard from "./components/MetricsDashboard";

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding:32, color:"#fca5a5", background:"rgba(239,68,68,.08)", border:"1px solid rgba(239,68,68,.25)", borderRadius:10, margin:32 }}>
          <div style={{ fontWeight:700, marginBottom:8 }}>Render error</div>
          <pre style={{ fontSize:12, whiteSpace:"pre-wrap", fontFamily:"monospace", color:"#fca5a5" }}>{this.state.error.message}</pre>
          <button onClick={() => this.setState({ error: null })} style={{ marginTop:16, padding:"6px 16px", background:"rgba(239,68,68,.15)", border:"1px solid rgba(239,68,68,.3)", borderRadius:6, color:"#fca5a5", cursor:"pointer" }}>
            Dismiss
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

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
        <ErrorBoundary>
          {tab === "submit"  && !incidentId && <IncidentForm onSubmitted={handleSubmitted} />}
          {tab === "triage"  && incidentId  && <TriageView incidentId={incidentId} onBack={() => go("recent")} />}
          {tab === "recent"  && !incidentId && <IncidentList onSelect={handleSelect} onNew={() => go("submit")} />}
          {tab === "metrics" && <MetricsDashboard />}
        </ErrorBoundary>
      </main>
    </div>
  );
}

