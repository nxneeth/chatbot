"""Builds the role-scoped facts the model may use, and plain template answers
that are used when no model is configured or a model answer fails checks.

Every number shown to the user comes from here, computed in Python."""
import re

from app.config import settings
from app.core.ledger import Ledger
from app.services.directory import Directory, group_stats, summarize


def fmt(n):
    if n is None:
        return "not recorded"
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    return str(n)


def pct(n):
    return "not recorded" if n is None else f"{fmt(n)}%"


# ---------------------------------------------------------------------- text
def student_lines(r, private=True):
    lines = [
        f"Name: {r['name']} ({r['student_code']})",
        f"Course: {r['course_name']} | Batch: {r['batch_code']} ({r['batch_status'] or 'status unknown'})",
        f"Instructor: {r['instructor_name'] or 'not assigned'}" + (f" ({r['instructor_email']})" if r.get("instructor_email") else ""),
        f"Schedule: {r['schedule'] or 'not set'}",
        f"Marks: {fmt(r['marks'])} out of {fmt(r['max_marks'])} | Result: {r['result'] or 'not recorded'} (pass mark {fmt(r['pass_mark'])})",
    ]
    if r["marks"] is not None:
        diff = r["marks"] - r["pass_mark"]
        lines.append(f"Marks {'above' if diff >= 0 else 'below'} pass mark by: {fmt(abs(diff))}")
    for a in r.get("assessments") or []:
        lines.append(f"Assessment {a['name']}: {fmt(a['score'])} out of {fmt(a['max'])}")
    if r["total_classes"]:
        missed = r["total_classes"] - (r["classes_attended"] or 0)
        lines.append(f"Attendance: {pct(r['attendance_pct'])} ({fmt(r['classes_attended'])} of {fmt(r['total_classes'])} classes, {fmt(missed)} missed)")
    else:
        lines.append("Attendance: not recorded")
    lines.append(f"Learning progress: {pct(r['learning_progress'])}")
    if private:
        if r.get("email"):
            lines.append(f"Email: {r['email']}")
        if r.get("phone"):
            lines.append(f"Phone: {r['phone']}")
    return lines


def summary_lines(title, s):
    lines = [f"{title}: {s['students']} students"]
    if s["average_marks"] is not None:
        lines.append(f"  Average marks {fmt(s['average_marks'])} | Pass rate {pct(s['pass_rate'])} ({s['passed']} passed, {s['failed']} failed)")
        lines.append(f"  Highest: {s['highest']['name']} ({s['highest']['code']}) {fmt(s['highest']['marks'])} | "
                     f"Lowest: {s['lowest']['name']} ({s['lowest']['code']}) {fmt(s['lowest']['marks'])}")
    if s["average_attendance"] is not None:
        lines.append(f"  Average attendance {pct(s['average_attendance'])} | Average learning progress {pct(s['average_progress'])}")
    lines.append("  Failing: " + (", ".join(s["failing_students"]) or "none"))
    lines.append(f"  Attendance below {fmt(s['low_attendance_threshold'])}%: " + (", ".join(s["low_attendance_students"]) or "none"))
    return lines


def table(rows, cols):
    head = "| " + " | ".join(c[0] for c in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = ["| " + " | ".join(str(c[1](r)) for c in cols) + " |" for r in rows]
    return "\n".join([head, sep, *body])


STUDENT_COLS = [
    ("ID", lambda r: r["student_code"]), ("Name", lambda r: r["name"]), ("Batch", lambda r: r["batch_code"]),
    ("Marks", lambda r: fmt(r["marks"])), ("Result", lambda r: r["result"] or "—"),
    ("Attendance", lambda r: pct(r["attendance_pct"])), ("Progress", lambda r: pct(r["learning_progress"])),
]


# ------------------------------------------------------------------- context
class Facts:
    """Collects the authorised data for one question."""

    def __init__(self, db, user):
        self.db = db
        self.dir = Directory(db)
        self.user = user  # {"user_id", "role", "name"}

    # student ----------------------------------------------------------
    def student_context(self):
        r = self.dir.student_row(self.user["user_id"])
        if not r:
            return {"text": "No academic record found for this student.", "row": None}
        directory = [f"{i['name']} teaches " + ", ".join(
            f"{b['batch_code']}" for b in self.dir.instructor_batches(i["instructor_code"])) for i in self.dir.instructors()]
        course = self.dir.course(r["course_code"]) or {}
        text = "\n".join([
            "STUDENT RECORD", *student_lines(r),
            "",
            "COURSE RULES",
            f"Pass mark for {r['course_name']}: {fmt(course.get('pass_mark'))} out of {fmt(course.get('max_marks'))}",
            f"Attendance below {fmt(settings.LOW_ATTENDANCE)}% is flagged as low",
            "",
            "PUBLIC FACULTY DIRECTORY (names and batches only)", *directory,
        ])
        return {"text": text, "row": r}

    # instructor ---------------------------------------------------------
    def instructor_context(self, focus_codes=()):
        uid = self.user["user_id"]
        batches = self.dir.instructor_batches(uid)
        rows = self.dir.instructor_student_rows(uid)
        if not batches:
            return {"text": "You have no batches assigned yet.", "rows": [], "batches": []}
        parts = ["YOUR BATCHES"]
        for b in batches:
            course = self.dir.course(b["course_code"]) or {}
            parts.append(f"Batch {b['batch_code']}: {course.get('name')} | {b.get('schedule') or 'no schedule'} | {b.get('status')}"
                         f" | pass mark {fmt(course.get('pass_mark'))}")
        stats = group_stats(rows, "batch_code")
        for code, s in stats.items():
            parts += summary_lines(f"Batch {code} summary", s)
        if len(batches) > 1:
            parts += summary_lines("All your students", summarize(rows))
        parts += ["", "YOUR STUDENTS", table(rows, STUDENT_COLS)]
        for r in rows:
            if r["student_code"] in focus_codes:
                parts += ["", f"DETAIL FOR {r['name']}", *student_lines(r, private=False)]
        return {"text": "\n".join(parts), "rows": rows, "batches": batches, "stats": stats}

    # admin -----------------------------------------------------------------
    def admin_context(self, route_topics=(), focus=None, include_table=True):
        focus = focus or {}
        rows = self.dir.student_rows()
        courses = self.dir.courses()
        batches = self.dir.batches()
        instructors = self.dir.instructors()
        admins = self.dir.admins()
        logins = self.dir.login_ids()
        cname = {c["course_code"]: c["name"] for c in courses}
        iname = {i["instructor_code"]: i["name"] for i in instructors}

        parts = [
            "LMS TOTALS",
            f"Students {len(rows)} | Instructors {len(instructors)} | Admins {len(admins)} | Courses {len(courses)} | "
            f"Batches {len(batches)} ({sum(1 for b in batches if b.get('status') == 'Active')} active, "
            f"{sum(1 for b in batches if b.get('status') != 'Active')} completed) | Accounts that can log in: {len(logins)}",
            "",
        ]
        parts += summary_lines("Whole institution", summarize(rows))
        parts.append("")
        parts.append("BY COURSE")
        for code, s in group_stats(rows, "course_code").items():
            c = next((x for x in courses if x["course_code"] == code), {})
            parts += summary_lines(f"{cname.get(code, code)} ({code}, pass mark {fmt(c.get('pass_mark'))})", s)
        parts.append("")
        parts.append("BY BATCH")
        bstats = group_stats(rows, "batch_code")
        for b in batches:
            s = bstats.get(b["batch_code"])
            head = (f"Batch {b['batch_code']} | {cname.get(b['course_code'])} | instructor {iname.get(b.get('instructor_code'), 'none')}"
                    f" | {b.get('schedule') or 'no schedule'} | {b.get('status')}"
                    + (f" | engagement score {fmt(b['engagement_score'])}" if b.get("engagement_score") is not None else ""))
            if s:
                parts += summary_lines(head, s)
            else:
                parts.append(head + ": 0 students")
        parts += ["", "INSTRUCTORS"]
        for i in instructors:
            teaches = [b["batch_code"] for b in batches if b.get("instructor_code") == i["instructor_code"]]
            parts.append(f"{i['instructor_code']} {i['name']} | {i.get('email') or 'no email'} | batches {', '.join(teaches) or 'none'}"
                         f" | login {'yes' if i['instructor_code'] in logins else 'no'}")
        parts += ["", "ADMINS"]
        for a in admins:
            parts.append(f"{a['admin_code']} {a['name']} | {a.get('email') or 'no email'} | {a.get('phone') or 'no phone'}"
                         f" | login {'yes' if a['admin_code'] in logins else 'no'}")
        if "ledger" in route_topics:
            v = Ledger(self.db).verify()
            parts += ["", "AUDIT LEDGER", f"Blocks: {v['blocks']} | Chain valid: {'yes' if v['valid'] else 'NO - ' + v['reason']}"]
            for blk in Ledger(self.db).list(limit=8):
                parts.append(f"#{blk['index']} {blk['timestamp']} {blk['actor']['user_id']} {blk['action']} {blk.get('target') or ''}")
        for code in focus.get("students", []):
            r = next((x for x in rows if x["student_code"] == code), None)
            if r:
                parts += ["", f"DETAIL FOR {r['name']}", *student_lines(r), f"Has login: {'yes' if r['has_login'] else 'no'}"]
        if include_table and len(rows) <= 60:
            parts += ["", "ALL STUDENTS", table(rows, STUDENT_COLS)]
        return {"text": "\n".join(parts), "rows": rows}


# ------------------------------------------------------------------ templates
def _wants(topics, *names):
    return bool(set(topics) & set(names))


def student_template(row, topics, course=None):
    if not row:
        return "I couldn't find an academic record for your account yet. Please contact the admin."
    out = []
    topics = set(topics)
    if "policy" in topics:
        topics.discard("marks")
    if _wants(topics, "marks"):
        line = f"You scored **{fmt(row['marks'])}/{fmt(row['max_marks'])}** in {row['course_name']}"
        if row["result"]:
            line += f", which is a **{row['result']}** (pass mark {fmt(row['pass_mark'])})."
        else:
            line = "Your marks haven't been recorded yet."
        out.append(line)
        for a in row.get("assessments") or []:
            out.append(f"- {a['name']}: {fmt(a['score'])}/{fmt(a['max'])}")
    if _wants(topics, "attendance"):
        if row["total_classes"]:
            missed = row["total_classes"] - row["classes_attended"]
            line = (f"Your attendance is **{pct(row['attendance_pct'])}**: {fmt(row['classes_attended'])} of "
                    f"{fmt(row['total_classes'])} classes ({fmt(missed)} missed).")
            if row["attendance_pct"] < settings.LOW_ATTENDANCE:
                line += f" That's below the {fmt(settings.LOW_ATTENDANCE)}% mark, so try not to miss more classes."
            out.append(line)
        else:
            out.append("Your attendance hasn't been recorded yet.")
    if _wants(topics, "progress"):
        out.append(f"Your learning progress in {row['course_name']} is **{pct(row['learning_progress'])}**.")
        if not _wants(topics, "marks", "attendance"):
            out.append(f"Marks: {fmt(row['marks'])}/{fmt(row['max_marks'])} ({row['result'] or 'not recorded'}) · "
                       f"Attendance: {pct(row['attendance_pct'])}")
    if _wants(topics, "schedule"):
        out.append(f"Your batch {row['batch_code']} meets **{row['schedule'] or 'on a schedule not set yet'}**"
                   f" (batch status: {row['batch_status']}).")
    if _wants(topics, "instructor"):
        out.append(f"Your instructor is **{row['instructor_name'] or 'not assigned yet'}**"
                   + (f" ({row['instructor_email']})." if row.get("instructor_email") else "."))
    if _wants(topics, "course", "profile"):
        out.append(f"You're enrolled in **{row['course_name']}**, batch **{row['batch_code']}** (ID {row['student_code']}).")
    if _wants(topics, "policy"):
        out.append(f"The pass mark for {row['course_name']} is **{fmt(row['pass_mark'])}** out of {fmt(row['max_marks'])}, "
                   f"and attendance below {fmt(settings.LOW_ATTENDANCE)}% is flagged as low.")
    if not out:
        out = [f"Here's where you stand in **{row['course_name']}** (batch {row['batch_code']}):",
               f"- Marks: {fmt(row['marks'])}/{fmt(row['max_marks'])} ({row['result'] or 'not recorded'})",
               f"- Attendance: {pct(row['attendance_pct'])}",
               f"- Learning progress: {pct(row['learning_progress'])}",
               f"- Instructor: {row['instructor_name'] or 'not assigned'}"]
    return "\n".join(out)


def person_template(r, private=False):
    lines = [f"**{r['name']}** ({r['student_code']}) · {r['course_name']}, batch {r['batch_code']}",
             (f"- Marks: {fmt(r['marks'])}/{fmt(r['max_marks'])} ({r['result']})" if r["marks"] is not None else "- Marks: not recorded yet"),
             f"- Attendance: {pct(r['attendance_pct'])}"
             + (f" ({fmt(r['classes_attended'])}/{fmt(r['total_classes'])} classes)" if r["total_classes"] else ""),
             f"- Learning progress: {pct(r['learning_progress'])}"]
    if private and (r.get("email") or r.get("phone")):
        lines.append(f"- Contact: {r.get('email') or ''} {r.get('phone') or ''}".rstrip())
    return "\n".join(lines)


def group_template(title, rows, topics, text):
    s = summarize(rows)
    t = text.lower()
    out = []
    if re.search(r"\b(low|below|poor)\b.*attendance|attendance.*\b(low|below|poor)\b", t):
        out.append(f"Students in {title} with attendance below {fmt(s['low_attendance_threshold'])}%: "
                   + (", ".join(s["low_attendance_students"]) or "none."))
    if re.search(r"\b(fail(ed|ing)?|at[- ]risk|struggling|weak)\b", t):
        out.append(f"Failing students in {title}: " + (", ".join(s["failing_students"]) or "none."))
    if re.search(r"\b(top|highest|best|topper)\b", t) and s["highest"]:
        out.append(f"Top scorer in {title}: **{s['highest']['name']}** ({s['highest']['code']}) with {fmt(s['highest']['marks'])}.")
    if re.search(r"\b(lowest|worst|bottom)\b", t) and s["lowest"]:
        out.append(f"Lowest score in {title}: **{s['lowest']['name']}** ({s['lowest']['code']}) with {fmt(s['lowest']['marks'])}.")
    if re.search(r"\b(list|show|who are|who is in|roster|all students)\b", t) and _wants(topics, "students") and not out:
        out.append(f"Students in {title}:\n\n" + table(rows[:20], STUDENT_COLS))
        if len(rows) > 20:
            out.append(f"…and {len(rows) - 20} more. The full list is in LMS Overview.")
    if not out or re.search(r"\b(average|summary|overview|how (is|are)|perform|stats)\b", t):
        out.append(f"**{title}**: {s['students']} students · average marks {fmt(s['average_marks'])} · "
                   f"pass rate {pct(s['pass_rate'])} · average attendance {pct(s['average_attendance'])} · "
                   f"average progress {pct(s['average_progress'])}.")
    return "\n\n".join(out)
