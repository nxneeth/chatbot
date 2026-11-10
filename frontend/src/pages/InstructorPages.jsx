import { useMemo, useState } from "react";
import { fmt } from "../lib/api.js";
import { AttendanceCell, Loading, ResultPill, Stat, StatusPill, SubPage, useApi } from "./common.jsx";

export function InstructorClass({ onBack }) {
  const s = useApi("/instructor/class");
  const [q, setQ] = useState("");
  const rows = useMemo(() => (s.data?.students || []).filter((r) =>
    `${r.name} ${r.student_code} ${r.batch_code}`.toLowerCase().includes(q.toLowerCase())), [s.data, q]);
  return (
    <SubPage badge="MY CLASS" title="Your students" sub="Everyone assigned to your batches." onBack={onBack}>
      <Loading state={s} />
      {s.data && (
        <>
          <div className="section stats" style={{ gridTemplateColumns: `repeat(${Math.min(4, Math.max(1, s.data.batches.length))}, 1fr)` }}>
            {s.data.batches.map((b) => (
              <div className="stat" key={b.batch_code}>
                <div className="stat-label">Batch {b.batch_code} · {b.course_name}</div>
                <div className="stat-value" style={{ fontSize: 22 }}>{s.data.by_batch[b.batch_code]?.students ?? 0} students</div>
                <div className="stat-note">{b.schedule || "No schedule"} · <StatusPill status={b.status} /></div>
              </div>
            ))}
          </div>
          <div className="section panel">
            <div className="toolbar">
              <h2 className="section-title" style={{ margin: 0 }}>Class list</h2>
              <span className="spacer" />
              <input className="search" placeholder="Search name or ID" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>ID</th><th>Name</th><th>Batch</th><th>Course</th><th>Progress</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.student_code}>
                      <td className="mono">{r.student_code}</td><td><b>{r.name}</b></td><td>{r.batch_code}</td>
                      <td>{r.course_name}</td><td className="num">{fmt(r.learning_progress, "%")}</td>
                    </tr>
                  ))}
                  {!rows.length && <tr><td colSpan={5} className="empty">No students found.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </SubPage>
  );
}

export function InstructorPerformance({ onBack }) {
  const s = useApi("/instructor/class");
  const sum = s.data?.summary;
  const threshold = s.data?.low_attendance_threshold ?? 75;
  return (
    <SubPage badge="CLASS PERFORMANCE" title="How your class is doing" sub="Marks, results, attendance and progress across your batches." onBack={onBack}>
      <Loading state={s} />
      {sum && (
        <>
          <div className="section stats">
            <Stat label="Average marks" value={fmt(sum.average_marks)} note={sum.highest ? `Top: ${sum.highest.name} (${fmt(sum.highest.marks)})` : ""} />
            <Stat label="Pass rate" value={fmt(sum.pass_rate, "%")} note={`${sum.passed} passed · ${sum.failed} failed`} />
            <Stat label="Average attendance" value={fmt(sum.average_attendance, "%")} bar={sum.average_attendance} />
            <Stat label="Average progress" value={fmt(sum.average_progress, "%")} bar={sum.average_progress} />
          </div>
          {(sum.failing_students.length > 0 || sum.low_attendance_students.length > 0) && (
            <div className="section notice">
              {sum.failing_students.length > 0 && <div><b>Below pass mark:</b> {sum.failing_students.join(", ")}</div>}
              {sum.low_attendance_students.length > 0 && <div><b>Attendance below {threshold}%:</b> {sum.low_attendance_students.join(", ")}</div>}
            </div>
          )}
          <div className="section panel">
            <h2 className="section-title">Student results</h2>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>ID</th><th>Name</th><th>Batch</th><th>Marks</th><th>Result</th><th>Attendance</th><th>Progress</th></tr></thead>
                <tbody>
                  {[...s.data.students].sort((a, b) => (b.marks ?? -1) - (a.marks ?? -1)).map((r) => (
                    <tr key={r.student_code}>
                      <td className="mono">{r.student_code}</td><td><b>{r.name}</b></td><td>{r.batch_code}</td>
                      <td className="num">{r.marks === null ? "—" : `${fmt(r.marks)}/${fmt(r.max_marks)}`}</td>
                      <td><ResultPill result={r.result} /></td>
                      <td className="num"><AttendanceCell pct={r.attendance_pct} threshold={threshold} /></td>
                      <td className="num">{fmt(r.learning_progress, "%")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </SubPage>
  );
}
