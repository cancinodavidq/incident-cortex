import React, { useState } from "react";

const s = {
  wrap:   { maxWidth:560, margin:"0 auto" },
  title:  { fontSize:20, fontWeight:700, letterSpacing:"-0.02em", marginBottom:4 },
  sub:    { fontSize:13, color:"var(--text2)", marginBottom:28 },
  field:  { marginBottom:20 },
  label:  { display:"block", fontSize:12, fontWeight:600, color:"var(--text2)", textTransform:"uppercase", letterSpacing:"0.06em", marginBottom:6 },
  input:  { width:"100%", background:"var(--surface2)", border:"1px solid var(--border2)", borderRadius:8, padding:"10px 14px", color:"var(--text)", fontSize:14, outline:"none", transition:"border-color .15s", display:"block" },
  textarea: { width:"100%", background:"var(--surface2)", border:"1px solid var(--border2)", borderRadius:8, padding:"10px 14px", color:"var(--text)", fontSize:14, outline:"none", resize:"vertical", minHeight:120, fontFamily:"inherit", transition:"border-color .15s", display:"block" },
  err:    { fontSize:12, color:"var(--red)", marginTop:5 },
  btn:    { width:"100%", padding:"12px", background:"var(--accent)", border:"none", borderRadius:8, color:"#fff", fontSize:14, fontWeight:600, letterSpacing:"-0.01em", transition:"opacity .15s", marginTop:8, cursor:"pointer" },
  errBox: { background:"rgba(239,68,68,0.08)", border:"1px solid rgba(239,68,68,0.3)", borderRadius:8, padding:"10px 14px", fontSize:13, color:"#fca5a5", marginBottom:16 },
  spinner: { width:16, height:16, border:"2px solid rgba(255,255,255,.3)", borderTopColor:"#fff", borderRadius:"50%", display:"inline-block", animation:"spin .6s linear infinite", marginRight:8, verticalAlign:"middle" },
};

export default function IncidentForm({ onSubmitted }) {
  const [form, setForm]   = useState({ title:"", description:"", reporter_email:"" });
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);

  const set = (k, v) => setForm(f => ({ ...f, [k]:v }));

  const validate = () => {
    const e = {};
    if (!form.title.trim())         e.title = "Required";
    if (!form.description.trim())   e.description = "Required";
    if (!form.reporter_email.trim()) e.reporter_email = "Required";
    else if (!form.reporter_email.includes("@")) e.reporter_email = "Invalid email";
    setErrors(e);
    return !Object.keys(e).length;
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!validate()) return;
    setLoading(true);
    try {
      const fd = new FormData();
      Object.entries(form).forEach(([k,v]) => fd.append(k, v));
      const r = await fetch("/api/incidents", { method:"POST", body:fd });
      if (!r.ok) { const d = await r.json(); setErrors({ _: d.detail || "Submission failed" }); setLoading(false); return; }
      const d = await r.json();
      setLoading(false);
      onSubmitted(d.incident_id);
    } catch(err) {
      setErrors({ _: "Network error: " + err.message });
      setLoading(false);
    }
  };

  return (
    <div style={s.wrap}>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <h1 style={s.title}>Report Incident</h1>
      <p style={s.sub}>Submit a new incident for automated SRE triage</p>

      {errors._ && <div style={s.errBox}>{errors._}</div>}

      <form onSubmit={submit}>
        <div style={s.field}>
          <label style={s.label}>Title</label>
          <input
            style={{...s.input, ...(errors.title ? {borderColor:"var(--red)"} : {})}}
            placeholder="e.g. Database connection timeout in production"
            value={form.title}
            onChange={e => set("title", e.target.value)}
            onFocus={e => e.target.style.borderColor="var(--accent)"}
            onBlur={e => e.target.style.borderColor = errors.title ? "var(--red)" : "var(--border2)"}
          />
          {errors.title && <div style={s.err}>{errors.title}</div>}
        </div>

        <div style={s.field}>
          <label style={s.label}>Description</label>
          <textarea
            style={{...s.textarea, ...(errors.description ? {borderColor:"var(--red)"} : {})}}
            placeholder="Describe what's happening — symptoms, affected services, timeline, error messages..."
            value={form.description}
            onChange={e => set("description", e.target.value)}
            onFocus={e => e.target.style.borderColor="var(--accent)"}
            onBlur={e => e.target.style.borderColor = errors.description ? "var(--red)" : "var(--border2)"}
            rows={6}
          />
          {errors.description && <div style={s.err}>{errors.description}</div>}
        </div>

        <div style={s.field}>
          <label style={s.label}>Reporter Email</label>
          <input
            type="text"
            inputMode="email"
            autoComplete="email"
            style={{...s.input, ...(errors.reporter_email ? {borderColor:"var(--red)"} : {})}}
            placeholder="you@company.com"
            value={form.reporter_email}
            onChange={e => set("reporter_email", e.target.value)}
            onFocus={e => e.target.style.borderColor="var(--accent)"}
            onBlur={e => e.target.style.borderColor = errors.reporter_email ? "var(--red)" : "var(--border2)"}
          />
          {errors.reporter_email && <div style={s.err}>{errors.reporter_email}</div>}
        </div>

        <button type="submit" style={{...s.btn, opacity: loading ? 0.7 : 1}} disabled={loading}>
          {loading && <span style={s.spinner} />}
          {loading ? "Submitting…" : "Submit Incident"}
        </button>
      </form>
    </div>
  );
}
