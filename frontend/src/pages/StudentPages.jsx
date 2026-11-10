import { fmt } from "../lib/api.js";
import { Loading, ResultPill, Stat, StatusPill, SubPage, useApi } from "./common.jsx";

export function StudentLearning({ onBack, openChat }) {
  const s = useApi("/student/overview");
  const r = s.data?.record;
  return (
    <SubPage badge="MY LEARNING" title="Your course" sub="Your enrolled course, batch, schedule and learning progress." onBack={onBack}>
      <Loading state={s} />
      {s.data && !r && <div className="section notice">No course record yet. Please contact the admin.</div>}
      {r && (
        <>
          <div className="section panel">
            <h2 className="section-title">{r.course_name}</h2>
            <dl className="kv">
              <dt>Batch</dt><dd>{r.batch_code} <StatusPill status={r.batch_status} /></dd>
              <dt>Schedule</dt><dd>{r.schedule || "Not set"}</dd>
              <dt>Instructor</dt><dd>{r.instructor_name || "Not assigned"}{r.instructor_email && <span className="muted"> · {r.instructor_email}</span>}</dd>
              <dt>Student ID</dt><dd>{r.student_code}</dd>
            </dl>
          </div>
          <div className="section stats" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Stat label="Learning progress" value={fmt(r.learning_progress, "%")} bar={r.learning_progress} note="Course material completed" />
            <div className="stat" style={{ display: "flex", flexDirection: "column" }}>
              <div className="stat-label">Need help with a topic?</div>
              <div style={{ marginTop: 12, color: "var(--muted)", fontSize: 15 }}>
                Ask the study assistant to explain a concept, give examples, or quiz you.
              </div>
              <div style={{ marginTop: "auto", paddingTop: 16 }}>
                <button className="btn" onClick={openChat}>Open Study Assistant</button>
              </div>
            </div>
          </div>
        </>
      )}
    </SubPage>
  );
}

export function StudentProgress({ onBack }) {
  const s = useApi("/student/overview");
  const r = s.data?.record;
  const threshold = s.data?.low_attendance_threshold ?? 75;
  return (
    <SubPage badge="MY PROGRESS" title="Marks, attendance & progress" sub="Your latest academic record." onBack={onBack}>
      <Loading state={s} />
      {r && (
        <>
          <div className="section stats">
            <Stat label="Marks" value={r.marks === null ? "—" : `${fmt(r.marks)}/${fmt(r.max_marks)}`}
              note={`Pass mark ${fmt(r.pass_mark)}`} bar={r.marks === null ? null : (r.marks / r.max_marks) * 100} />
            <div className="stat">
              <div className="stat-label">Result</div>
              <div className="stat-value" style={{ fontSize: 24, marginTop: 16 }}><ResultPill result={r.result} /></div>
            </div>
            <Stat label="Attendance" value={fmt(r.attendance_pct, "%")} bar={r.attendance_pct}
              note={r.total_classes ? `${r.classes_attended} of ${r.total_classes} classes` : "Not recorded"} />
            <Stat label="Learning progress" value={fmt(r.learning_progress, "%")} bar={r.learning_progress} />
          </div>
          {r.attendance_pct !== null && r.attendance_pct < threshold && (
            <div className="section notice err">Your attendance is below {threshold}%. Try not to miss upcoming classes.</div>
          )}
          {r.assessments?.length > 0 && (
            <div className="section panel">
              <h2 className="section-title">Assessments</h2>
              <table className="data">
                <thead><tr><th>Assessment</th><th>Score</th></tr></thead>
                <tbody>{r.assessments.map((a) => <tr key={a.name}><td>{a.name}</td><td className="num">{fmt(a.score)}/{fmt(a.max)}</td></tr>)}</tbody>
              </table>
            </div>
          )}
        </>
      )}
    </SubPage>
  );
}
