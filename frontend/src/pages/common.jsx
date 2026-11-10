import { useEffect, useState } from "react";
import { api, fmt } from "../lib/api.js";

export function useApi(path, deps = []) {
  const [state, setState] = useState({ data: null, error: "", loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true }));
    api(path)
      .then((data) => live && setState({ data, error: "", loading: false }))
      .catch((e) => live && setState({ data: null, error: e.message, loading: false }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}

export function SubPage({ badge, title, sub, onBack, children }) {
  return (
    <main className="page">
      <div className="container">
        <button className="back-link" onClick={onBack}>← Back to dashboard</button>
        <div><span className="badge">{badge}</span></div>
        <h1 className="page-title sm">{title}</h1>
        {sub && <p className="page-sub">{sub}</p>}
        {children}
      </div>
    </main>
  );
}

export function Loading({ state }) {
  if (state.loading && !state.data) return <div className="section panel empty">Loading…</div>;
  if (state.error) return <div className="section notice err">{state.error}</div>;
  return null;
}

export function Stat({ label, value, note, bar }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {bar !== undefined && bar !== null && (
        <div className="progress-track"><div className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, bar))}%` }} /></div>
      )}
      {note && <div className="stat-note">{note}</div>}
    </div>
  );
}

export function ResultPill({ result }) {
  if (!result) return <span className="pill muted">Not recorded</span>;
  return <span className={`pill ${result === "Pass" ? "pass" : "fail"}`}>{result}</span>;
}

export function AttendanceCell({ pct, threshold }) {
  if (pct === null || pct === undefined) return <span className="muted">—</span>;
  return <span className={pct < threshold ? "pill warn" : ""}>{fmt(pct, "%")}</span>;
}

export function StatusPill({ status }) {
  return <span className={`pill ${status === "Active" ? "active" : "completed"}`}>{status || "—"}</span>;
}
