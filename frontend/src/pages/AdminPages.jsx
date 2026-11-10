import { useEffect, useMemo, useState } from "react";
import Modal from "../components/Modal.jsx";
import { api, fmt } from "../lib/api.js";
import { AttendanceCell, Loading, ResultPill, Stat, StatusPill, SubPage, useApi } from "./common.jsx";

/* ------------------------------------------------------------------ dialogs */

// Shows the server's summary of an action, then runs it on Confirm.
function ActionDialog({ action, onClose, onDone }) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    api("/admin/actions/preview", { method: "POST", body: action })
      .then((p) => setState({ preview: p }))
      .catch((e) => setState({ error: e.message }));
  }, [action]);

  async function run() {
    setState((s) => ({ ...s, running: true }));
    try {
      const res = await api("/admin/actions", { method: "POST", body: action });
      setState({ result: res });
      onDone();
    } catch (e) {
      setState((s) => ({ ...s, running: false, error: e.message }));
    }
  }

  const p = state.preview;
  return (
    <Modal
      title={state.result ? "Done" : p?.destructive ? "Confirm removal" : "Confirm change"}
      onClose={onClose}
      actions={state.result || state.error && !p ? (
        <button className="btn" onClick={onClose}>Close</button>
      ) : (
        <>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className={`btn ${p?.destructive ? "danger" : ""}`} disabled={!p || state.running} onClick={run}>
            {state.running ? "Applying…" : p?.destructive ? "Delete" : "Confirm"}
          </button>
        </>
      )}
    >
      {state.loading && <p className="muted">Checking…</p>}
      {state.error && <div className="notice err" style={{ marginTop: 16 }}>{state.error}</div>}
      {p && !state.result && (
        <>
          <ul className="summary-list">{p.summary.map((l) => <li key={l}>{l}</li>)}</ul>
          {p.destructive && <div className="notice err" style={{ marginTop: 14 }}>This cannot be undone.</div>}
        </>
      )}
      {state.result && (
        <div className="notice ok" style={{ marginTop: 16 }}>
          {state.result.message}
          {state.result.data?.temporary_password && (
            <div style={{ marginTop: 8 }}>
              Temporary password: <b className="mono" style={{ fontSize: 15 }}>{state.result.data.temporary_password}</b>
              <div className="muted" style={{ fontSize: 13 }}>Copy it now; it won't be shown again.</div>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

// Generic form whose submit builds an action for ActionDialog.
function FormDialog({ title, fields, initial = {}, onClose, onSubmit }) {
  const [values, setValues] = useState(() => Object.fromEntries(fields.map((f) => [f.name, initial[f.name] ?? f.default ?? ""])));
  const [error, setError] = useState("");
  const set = (k, v) => setValues((s) => ({ ...s, [k]: v }));
  function submit(e) {
    e.preventDefault();
    const missing = fields.find((f) => f.required && !String(values[f.name] ?? "").trim());
    if (missing) {
      setError(`${missing.label} is required`);
      return;
    }
    onSubmit(values);
  }
  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit}>
        {fields.map((f) => (
          <label className="field" key={f.name}>
            <span className="field-label">{f.label}{f.required && " *"}</span>
            {f.options ? (
              <select className="input" value={values[f.name]} onChange={(e) => set(f.name, e.target.value)}>
                {!f.required && <option value="">—</option>}
                {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            ) : (
              <input className="input" type={f.type || "text"} placeholder={f.placeholder} value={values[f.name]}
                onChange={(e) => set(f.name, e.target.value)} />
            )}
            {f.hint && <span className="muted" style={{ fontSize: 13, display: "block", marginTop: 6 }}>{f.hint}</span>}
          </label>
        ))}
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn">Continue</button>
        </div>
      </form>
    </Modal>
  );
}

const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "" && v !== null && v !== undefined));

/* ------------------------------------------------------------------ overview */

const TABS = [
  ["students", "Students"], ["instructors", "Instructors"], ["admins", "Admins"],
  ["courses", "Courses & batches"], ["import", "Import CSV"], ["ledger", "Audit ledger"],
];

export function AdminOverview({ onBack }) {
  const [tab, setTab] = useState("students");
  const [dialog, setDialog] = useState(null);
  const [version, setVersion] = useState(0);
  const refresh = () => setVersion((v) => v + 1);
  const batches = useApi("/admin/batches", [version]);
  const courses = useApi("/admin/courses", [version]);
  const instructors = useApi("/admin/users?role=instructor", [version]);
  const ctx = {
    batches: batches.data || [], courses: courses.data || [], instructors: instructors.data || [], version,
    act: (action) => setDialog({ kind: "action", action }),
    form: (cfg) => setDialog({ kind: "form", ...cfg }),
  };
  return (
    <SubPage badge="LMS OVERVIEW" title="Manage the LMS" sub="Add, edit and remove people, courses and batches. Every change is confirmed and written to the audit ledger." onBack={onBack}>
      <div className="tabs">
        {TABS.map(([k, label]) => <button key={k} className={`tab ${tab === k ? "on" : ""}`} onClick={() => setTab(k)}>{label}</button>)}
      </div>
      <div className="section" style={{ marginTop: 24 }}>
        {tab === "students" && <PeopleTab role="student" ctx={ctx} />}
        {tab === "instructors" && <PeopleTab role="instructor" ctx={ctx} />}
        {tab === "admins" && <PeopleTab role="admin" ctx={ctx} />}
        {tab === "courses" && <CoursesTab ctx={ctx} />}
        {tab === "import" && <ImportTab ctx={ctx} onDone={refresh} />}
        {tab === "ledger" && <LedgerTab version={version} />}
      </div>
      {dialog?.kind === "form" && (
        <FormDialog {...dialog} onClose={() => setDialog(null)}
          onSubmit={(values) => setDialog({ kind: "action", action: dialog.build(values) })} />
      )}
      {dialog?.kind === "action" && <ActionDialog action={dialog.action} onClose={() => setDialog(null)} onDone={refresh} />}
    </SubPage>
  );
}

function PeopleTab({ role, ctx }) {
  const s = useApi(`/admin/users?role=${role}`, [ctx.version]);
  const [q, setQ] = useState("");
  const idKey = { student: "student_code", instructor: "instructor_code", admin: "admin_code" }[role];
  const rows = useMemo(() => (s.data || []).filter((r) =>
    `${r.name} ${r[idKey]} ${r.batch_code || ""} ${r.email || ""}`.toLowerCase().includes(q.toLowerCase())), [s.data, q, idKey]);
  const batchOptions = ctx.batches.map((b) => ({ value: b.batch_code, label: `${b.batch_code} · ${ctx.courses.find((c) => c.course_code === b.course_code)?.name || b.course_code}` }));
  const label = { student: "student", instructor: "instructor", admin: "admin" }[role];

  const baseFields = [
    { name: "name", label: "Full name", required: true },
    { name: "email", label: "Email", type: "email" },
    { name: "phone", label: "Phone" },
  ];

  function add() {
    const fields = [...baseFields];
    if (role === "student") fields.push({ name: "batch_code", label: "Batch", options: batchOptions, required: true, default: batchOptions[0]?.value });
    if (role === "instructor") fields.push({ name: "batch_code", label: "Teaches batch (optional)", options: batchOptions });
    fields.push({ name: "password", label: "Password", type: "text", hint: "Leave empty to generate a temporary password." });
    ctx.form({
      title: `Add ${label}`, fields,
      build: (v) => {
        const payload = clean({ role, name: v.name, email: v.email, phone: v.phone, password: v.password });
        if (role === "student") payload.batch_code = v.batch_code;
        if (role === "instructor" && v.batch_code) payload.batch_codes = [v.batch_code];
        return { type: "create_user", payload };
      },
    });
  }

  function edit(r) {
    const fields = [...baseFields];
    if (role === "student") {
      fields.push({ name: "batch_code", label: "Batch", options: batchOptions, required: true });
      fields.push({ name: "learning_progress", label: "Learning progress (%)", type: "number" });
    }
    ctx.form({
      title: `Edit ${r.name}`, fields, initial: { ...r, email: r.email || "", phone: r.phone || "" },
      build: (v) => {
        const changed = {};
        for (const f of fields) {
          const before = r[f.name] ?? "";
          if (String(v[f.name]) !== String(before)) changed[f.name] = f.type === "number" ? Number(v[f.name]) : v[f.name];
        }
        return { type: "update_user", payload: { user_id: r[idKey], fields: changed } };
      },
    });
  }

  function marks(r) {
    ctx.form({
      title: `Marks for ${r.name}`, initial: { marks: r.marks ?? "" },
      fields: [{ name: "marks", label: `Marks (out of ${r.max_marks ?? 100})`, type: "number", required: true }],
      build: (v) => ({ type: "record_marks", payload: { student_code: r.student_code, marks: Number(v.marks) } }),
    });
  }

  function attendance(r) {
    ctx.form({
      title: `Attendance for ${r.name}`, initial: { classes_attended: r.classes_attended ?? "", total_classes: r.total_classes ?? "" },
      fields: [
        { name: "classes_attended", label: "Classes attended", type: "number", required: true },
        { name: "total_classes", label: "Total classes", type: "number", required: true },
      ],
      build: (v) => ({ type: "record_attendance", payload: { student_code: r.student_code, classes_attended: Number(v.classes_attended), total_classes: Number(v.total_classes) } }),
    });
  }

  return (
    <div className="panel">
      <div className="toolbar">
        <input className="search" placeholder={`Search ${label}s`} value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{rows.length} {label}{rows.length === 1 ? "" : "s"}</span>
        <span className="spacer" />
        <button className="btn" onClick={add}>+ Add {label}</button>
      </div>
      <Loading state={s} />
      {s.data && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>ID</th><th>Name</th>
                {role === "student" && <><th>Course</th><th>Batch</th><th>Marks</th><th>Attendance</th></>}
                {role === "instructor" && <><th>Email</th><th>Batches</th></>}
                {role === "admin" && <><th>Email</th><th>Phone</th></>}
                <th>Login</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r[idKey]}>
                  <td className="mono">{r[idKey]}</td>
                  <td><b>{r.name}</b>{role === "student" && r.email && <div className="muted" style={{ fontSize: 13 }}>{r.email}</div>}</td>
                  {role === "student" && <>
                    <td>{r.course_name}</td><td>{r.batch_code}</td>
                    <td className="num">{r.marks === null ? "—" : fmt(r.marks)} {r.result && <ResultPill result={r.result} />}</td>
                    <td className="num"><AttendanceCell pct={r.attendance_pct} threshold={75} /></td>
                  </>}
                  {role === "instructor" && <><td>{r.email || "—"}</td><td>{r.batches.join(", ") || "—"}</td></>}
                  {role === "admin" && <><td>{r.email || "—"}</td><td>{r.phone || "—"}</td></>}
                  <td>{r.has_login ? <span className={`pill ${r.active ? "yes" : "no"}`}>{r.active ? "Active" : "Disabled"}</span> : <span className="pill muted">None</span>}</td>
                  <td>
                    <div className="row-actions">
                      <button className="btn-sm" onClick={() => edit(r)}>Edit</button>
                      {role === "student" && <button className="btn-sm" onClick={() => marks(r)}>Marks</button>}
                      {role === "student" && <button className="btn-sm" onClick={() => attendance(r)}>Attendance</button>}
                      <button className="btn-sm" onClick={() => ctx.act({ type: "reset_password", payload: { user_id: r[idKey] } })}>
                        {r.has_login ? "Reset password" : "Create login"}
                      </button>
                      {r.has_login && (
                        <button className="btn-sm" onClick={() => ctx.act({ type: "update_user", payload: { user_id: r[idKey], fields: { active: !r.active } } })}>
                          {r.active ? "Disable" : "Enable"}
                        </button>
                      )}
                      <button className="btn-sm danger" onClick={() => ctx.act({ type: "delete_user", payload: { user_id: r[idKey] } })}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={9} className="empty">No {label}s found.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CoursesTab({ ctx }) {
  const courseOptions = ctx.courses.map((c) => ({ value: c.course_code, label: `${c.course_code} · ${c.name}` }));
  const insOptions = ctx.instructors.map((i) => ({ value: i.instructor_code, label: `${i.instructor_code} · ${i.name}` }));
  const statusOptions = [{ value: "Active", label: "Active" }, { value: "Completed", label: "Completed" }];
  const insName = (code) => ctx.instructors.find((i) => i.instructor_code === code)?.name || "—";
  return (
    <>
      <div className="panel">
        <div className="toolbar">
          <h2 className="section-title" style={{ margin: 0 }}>Courses</h2>
          <span className="spacer" />
          <button className="btn" onClick={() => ctx.form({
            title: "Add course",
            fields: [{ name: "name", label: "Course name", required: true }, { name: "pass_mark", label: "Pass mark", type: "number", default: 40 },
              { name: "max_marks", label: "Max marks", type: "number", default: 100 }],
            build: (v) => ({ type: "create_course", payload: { name: v.name, pass_mark: Number(v.pass_mark), max_marks: Number(v.max_marks) } }),
          })}>+ Add course</button>
        </div>
        <table className="data">
          <thead><tr><th>Code</th><th>Name</th><th>Also known as</th><th>Pass mark</th><th>Batches</th><th>Actions</th></tr></thead>
          <tbody>
            {ctx.courses.map((c) => (
              <tr key={c.course_code}>
                <td className="mono">{c.course_code}</td><td><b>{c.name}</b></td>
                <td className="muted">{(c.aliases || []).filter((a) => a !== c.name).join(", ") || "—"}</td>
                <td className="num">{fmt(c.pass_mark)}/{fmt(c.max_marks)}</td>
                <td>{ctx.batches.filter((b) => b.course_code === c.course_code).map((b) => b.batch_code).join(", ") || "—"}</td>
                <td><div className="row-actions">
                  <button className="btn-sm" onClick={() => ctx.form({
                    title: `Edit ${c.name}`, initial: c,
                    fields: [{ name: "name", label: "Course name", required: true }, { name: "pass_mark", label: "Pass mark", type: "number", required: true },
                      { name: "max_marks", label: "Max marks", type: "number", required: true }],
                    build: (v) => ({ type: "update_course", payload: { course_code: c.course_code, fields: { name: v.name, pass_mark: Number(v.pass_mark), max_marks: Number(v.max_marks) } } }),
                  })}>Edit</button>
                  <button className="btn-sm danger" onClick={() => ctx.act({ type: "delete_course", payload: { course_code: c.course_code } })}>Delete</button>
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <div className="toolbar">
          <h2 className="section-title" style={{ margin: 0 }}>Batches</h2>
          <span className="spacer" />
          <button className="btn" onClick={() => ctx.form({
            title: "Add batch",
            fields: [{ name: "batch_code", label: "Batch code", required: true, placeholder: "e.g. A4" },
              { name: "course_code", label: "Course", options: courseOptions, required: true, default: courseOptions[0]?.value },
              { name: "instructor_code", label: "Instructor", options: insOptions },
              { name: "schedule", label: "Schedule", placeholder: "Mon, Wed | 10:00 AM - 11:00 AM" },
              { name: "status", label: "Status", options: statusOptions, required: true, default: "Active" }],
            build: (v) => ({ type: "create_batch", payload: clean(v) }),
          })}>+ Add batch</button>
        </div>
        <table className="data">
          <thead><tr><th>Batch</th><th>Course</th><th>Instructor</th><th>Schedule</th><th>Students</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {ctx.batches.map((b) => (
              <tr key={b.batch_code}>
                <td><b>{b.batch_code}</b></td>
                <td>{ctx.courses.find((c) => c.course_code === b.course_code)?.name}</td>
                <td>{insName(b.instructor_code)}</td><td className="muted">{b.schedule || "—"}</td>
                <td className="num">{b.students}</td><td><StatusPill status={b.status} /></td>
                <td><div className="row-actions">
                  <button className="btn-sm" onClick={() => ctx.form({
                    title: `Edit batch ${b.batch_code}`, initial: { ...b, instructor_code: b.instructor_code || "" },
                    fields: [{ name: "instructor_code", label: "Instructor", options: insOptions },
                      { name: "schedule", label: "Schedule" }, { name: "status", label: "Status", options: statusOptions, required: true }],
                    build: (v) => {
                      const fields = {};
                      for (const k of ["instructor_code", "schedule", "status"]) if ((v[k] || "") !== (b[k] || "")) fields[k] = v[k] || null;
                      return { type: "update_batch", payload: { batch_code: b.batch_code, fields } };
                    },
                  })}>Edit</button>
                  <button className="btn-sm danger" onClick={() => ctx.act({ type: "delete_batch", payload: { batch_code: b.batch_code } })}>Delete</button>
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function ImportTab({ onDone }) {
  const [role, setRole] = useState("student");
  const [csv, setCsv] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sample = role === "student" ? "name,email,phone,batch_code,password\nRiya Das,riya@example.com,9876500001,A1,\nTom Mathew,,,B2,"
    : "name,email,phone,password\nDr. Sameer Khan,sameer.khan@university.edu,,";

  async function run(dryRun) {
    setBusy(true);
    setError("");
    try {
      const res = await api("/admin/import", { method: "POST", body: { role, csv, dry_run: dryRun } });
      setResult({ ...res, dryRun });
      if (!dryRun && res.ok) onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h2 className="section-title">Bulk import</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Paste CSV or choose a file. Columns: <span className="mono">name, email, phone{role === "student" ? ", batch_code" : ""}, password</span>.
        Leave password empty to generate temporary ones. Nothing is imported if any row has an error.
      </p>
      <div className="toolbar">
        <select className="input" style={{ width: 200, height: 42 }} value={role} onChange={(e) => { setRole(e.target.value); setResult(null); }}>
          <option value="student">Students</option>
          <option value="instructor">Instructors</option>
        </select>
        <input type="file" accept=".csv,text/csv" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setCsv(await f.text()); }} />
        <span className="spacer" />
        <button className="btn ghost" onClick={() => setCsv(sample)}>Insert example</button>
      </div>
      <textarea className="input" value={csv} onChange={(e) => { setCsv(e.target.value); setResult(null); }} placeholder={sample} />
      <div className="toolbar" style={{ marginTop: 14, marginBottom: 0 }}>
        <button className="btn ghost" disabled={!csv.trim() || busy} onClick={() => run(true)}>Check file</button>
        <button className="btn" disabled={!csv.trim() || busy || !(result?.dryRun && result.ok)} onClick={() => run(false)}>Import</button>
      </div>
      {error && <div className="notice err" style={{ marginTop: 16 }}>{error}</div>}
      {result && result.errors.length > 0 && (
        <div className="notice err" style={{ marginTop: 16 }}>
          {result.errors.map((e) => <div key={e.line}>Line {e.line} ({e.name || "no name"}): {e.error}</div>)}
        </div>
      )}
      {result?.dryRun && result.ok && <div className="notice ok" style={{ marginTop: 16 }}>{result.valid} rows look good. Click Import to add them.</div>}
      {result && !result.dryRun && result.ok && (
        <div className="section">
          <div className="notice ok">Imported {result.created.length} {role}s. Copy the temporary passwords now; they won't be shown again.</div>
          <table className="data" style={{ marginTop: 12 }}>
            <thead><tr><th>ID</th><th>Name</th><th>Temporary password</th></tr></thead>
            <tbody>{result.created.map((c) => <tr key={c.user_id}><td className="mono">{c.user_id}</td><td>{c.name}</td><td className="mono">{c.temporary_password || "(set in file)"}</td></tr>)}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function LedgerTab({ version }) {
  const [tick, setTick] = useState(0);
  const ledger = useApi("/admin/ledger?limit=100", [version, tick]);
  const verify = useApi("/admin/ledger/verify", [version, tick]);
  const checkpoints = useApi("/admin/ledger/checkpoints", [version, tick]);
  const [msg, setMsg] = useState("");
  async function checkpoint() {
    try {
      const c = await api("/admin/ledger/checkpoints", { method: "POST" });
      setMsg(`Checkpoint saved at block ${c.blocks - 1}: ${c.head_hash.slice(0, 16)}…`);
      setTick((t) => t + 1);
    } catch (e) {
      setMsg(e.message);
    }
  }
  const v = verify.data;
  return (
    <>
      <div className="stats" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
        <Stat label="Chain status" value={v ? (v.valid ? "Intact" : "Broken") : "…"}
          note={v ? (v.valid ? "Every block's hash checks out" : v.reason) : ""} />
        <Stat label="Blocks" value={v?.blocks ?? "…"} note="Each change is one block" />
        <div className="stat">
          <div className="stat-label">Checkpoint</div>
          <div style={{ marginTop: 12, fontSize: 14, color: "var(--muted)" }}>Records the current head hash. Ready to anchor on a public blockchain.</div>
          <button className="btn" style={{ marginTop: 14 }} onClick={checkpoint}>Create checkpoint</button>
        </div>
      </div>
      {msg && <div className="notice" style={{ marginTop: 16 }}>{msg}</div>}
      <div className="panel" style={{ marginTop: 20 }}>
        <h2 className="section-title">Change history</h2>
        <Loading state={ledger} />
        {ledger.data && (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>#</th><th>Time (UTC)</th><th>By</th><th>Action</th><th>Target</th><th>Hash</th></tr></thead>
              <tbody>
                {ledger.data.blocks.map((b) => (
                  <tr key={b.index}>
                    <td className="num">{b.index}</td><td className="muted">{b.timestamp.replace("T", " ").replace("+00:00", "")}</td>
                    <td className="mono">{b.actor.user_id}</td><td>{b.action.replace(/_/g, " ")}</td>
                    <td className="mono">{b.target || "—"}</td>
                    <td className="mono" title={`hash ${b.hash}\nprev ${b.prev_hash}`}>{b.hash.slice(0, 12)}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {checkpoints.data?.length > 0 && (
        <div className="panel" style={{ marginTop: 20 }}>
          <h2 className="section-title">Checkpoints</h2>
          <table className="data">
            <thead><tr><th>Created</th><th>By</th><th>Blocks</th><th>Head hash</th><th>Chain tx</th></tr></thead>
            <tbody>{checkpoints.data.map((c) => (
              <tr key={c.created_at + c.head_hash}><td className="muted">{c.created_at.replace("T", " ").replace("+00:00", "")}</td>
                <td className="mono">{c.created_by}</td><td className="num">{c.blocks}</td>
                <td className="mono">{c.head_hash.slice(0, 20)}…</td><td className="muted">{c.chain_tx || "not anchored"}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </>
  );
}

/* --------------------------------------------------------------- performance */

export function AdminPerformance({ onBack }) {
  const s = useApi("/admin/overview");
  const d = s.data;
  const t = d?.low_attendance_threshold ?? 75;
  return (
    <SubPage badge="PERFORMANCE" title="Institution performance" sub="Academic outcomes by course and batch, with the instructor for each batch." onBack={onBack}>
      <Loading state={s} />
      {d && (
        <>
          <div className="section stats">
            <Stat label="Students" value={d.totals.students} note={`${d.totals.instructors} instructors · ${d.totals.courses} courses`} />
            <Stat label="Average marks" value={fmt(d.summary.average_marks)} note={`Pass rate ${fmt(d.summary.pass_rate, "%")}`} />
            <Stat label="Average attendance" value={fmt(d.summary.average_attendance, "%")} bar={d.summary.average_attendance} />
            <Stat label="Batches" value={d.totals.batches} note={`${d.totals.active_batches} active`} />
          </div>
          {(d.summary.failing_students.length > 0 || d.summary.low_attendance_students.length > 0) && (
            <div className="section notice">
              {d.summary.failing_students.length > 0 && <div><b>Below pass mark:</b> {d.summary.failing_students.join(", ")}</div>}
              {d.summary.low_attendance_students.length > 0 && <div><b>Attendance below {t}%:</b> {d.summary.low_attendance_students.join(", ")}</div>}
            </div>
          )}
          <div className="section panel">
            <h2 className="section-title">By course</h2>
            <table className="data">
              <thead><tr><th>Course</th><th>Students</th><th>Avg marks</th><th>Pass rate</th><th>Avg attendance</th><th>Avg progress</th></tr></thead>
              <tbody>{d.courses.map((c) => (
                <tr key={c.course_code}><td><b>{c.name}</b> <span className="muted mono">{c.course_code}</span></td>
                  <td className="num">{c.stats?.students ?? 0}</td><td className="num">{fmt(c.stats?.average_marks)}</td>
                  <td className="num">{fmt(c.stats?.pass_rate, "%")}</td><td className="num">{fmt(c.stats?.average_attendance, "%")}</td>
                  <td className="num">{fmt(c.stats?.average_progress, "%")}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <div className="section panel">
            <h2 className="section-title">By batch</h2>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Batch</th><th>Course</th><th>Instructor</th><th>Students</th><th>Avg marks</th><th>Pass rate</th><th>Avg attendance</th><th>Status</th></tr></thead>
                <tbody>{d.batches.map((b) => (
                  <tr key={b.batch_code}><td><b>{b.batch_code}</b></td><td>{b.course_name}</td><td>{b.instructor_name || "—"}</td>
                    <td className="num">{b.stats?.students ?? 0}</td><td className="num">{fmt(b.stats?.average_marks)}</td>
                    <td className="num">{b.stats ? <span className={b.stats.pass_rate < 50 ? "pill fail" : ""}>{fmt(b.stats.pass_rate, "%")}</span> : "—"}</td>
                    <td className="num"><AttendanceCell pct={b.stats?.average_attendance} threshold={t} /></td>
                    <td><StatusPill status={b.status} /></td></tr>
                ))}</tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </SubPage>
  );
}
