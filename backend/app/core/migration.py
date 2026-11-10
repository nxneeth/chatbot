"""Converts the original LMS collections into the EduLayne v2 schema.

Old collections: students, marks, attendance, batches, course, instructors,
admins, batch_analytics.

Changes made (see README "Data model"):
* courses are referenced by course_code everywhere; display names and
  aliases live only in `courses` (fixes "AI" vs "Artificial Intelligence").
* batches hold course_code + instructor_code (single source of truth).
* marks / attendance keep only student_code + course_code + their numbers;
  names, batch and course text are no longer copied into them.
* attendance_percentage and result are computed, not stored.
* learning_progress "48%" becomes the number 48.
* batch_analytics is dropped (computed live); engagement_score is kept on
  the batch so the value is not lost.
* new: users (logins), counters (next IDs), audit_ledger.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

LEGACY_COLLECTIONS = ["students", "marks", "attendance", "batches", "course", "instructors", "admins", "batch_analytics"]
NEW_COLLECTIONS = ["courses", "batches", "students", "instructors", "admins", "marks", "attendance", "users", "counters"]

EXTRA_ALIASES = {
    "AI": ["Artificial Intelligence", "A.I."],
    "Cybersecurity": ["Cyber Security", "Cyber-security", "Infosec"],
    "DSA": ["Data Structures and Algorithms", "Data Structures & Algorithms", "Data Structures"],
    "Data Science": ["DataScience"],
}


def _strip_ext_json(value):
    """Turn Compass extended JSON ({"$oid": ...}, {"$numberInt": ...}) into plain values."""
    if isinstance(value, dict):
        if len(value) == 1:
            (k, v), = value.items()
            if k in ("$numberInt", "$numberLong"):
                return int(v)
            if k == "$numberDouble":
                return float(v)
            if k == "$oid":
                return v
            if k == "$date":
                return _strip_ext_json(v)
        return {k: _strip_ext_json(v) for k, v in value.items() if k != "_id"}
    if isinstance(value, list):
        return [_strip_ext_json(v) for v in value]
    return value


def load_legacy_json(directory: Path) -> dict:
    """Load Compass exports named like 'LMS.students.json' from a folder."""
    data = {}
    for name in LEGACY_COLLECTIONS:
        matches = list(Path(directory).glob(f"*{name}.json"))
        matches = [m for m in matches if re.search(rf"(^|\.){re.escape(name)}\.json$", m.name)]
        data[name] = _strip_ext_json(json.loads(matches[0].read_text())) if matches else []
    return data


def _num(text):
    if text is None or text == "":
        return None
    if isinstance(text, (int, float)):
        return text
    m = re.search(r"-?\d+(\.\d+)?", str(text))
    if not m:
        return None
    n = float(m.group())
    return int(n) if n.is_integer() else n


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def transform(old: dict, default_pass_mark: float = 40, now: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    warnings = []

    # ---- courses ------------------------------------------------------
    courses, alias_to_code = [], {}
    for c in sorted(old.get("course", []), key=lambda x: x["course_code"]):
        name = c["course"]
        aliases = sorted({name, *EXTRA_ALIASES.get(name, [])})
        courses.append({
            "course_code": c["course_code"],
            "name": name,
            "aliases": aliases,
            "pass_mark": default_pass_mark,
            "max_marks": 100,
            "created_at": now,
        })
        for a in aliases + [c["course_code"]]:
            alias_to_code[_norm(a)] = c["course_code"]

    def course_code(name):
        code = alias_to_code.get(_norm(name))
        if code is None and name:
            warnings.append(f"Unknown course name '{name}'")
        return code

    # ---- instructors ----------------------------------------------------
    instructors, name_to_ins = [], {}
    for i in sorted(old.get("instructors", []), key=lambda x: x["instructor_code"]):
        instructors.append({
            "instructor_code": i["instructor_code"],
            "name": i["name"],
            "email": i.get("email"),
            "phone": i.get("phone"),
            "created_at": now,
        })
        name_to_ins[_norm(i["name"])] = i["instructor_code"]
    ins_by_batch = {i.get("batch"): i["instructor_code"] for i in old.get("instructors", []) if i.get("batch")}

    # ---- batches --------------------------------------------------------
    engagement = {a["batch_id"]: a.get("engagement_score") for a in old.get("batch_analytics", [])}
    batches = []
    for b in sorted(old.get("batches", []), key=lambda x: x["batch"]):
        ins_code = name_to_ins.get(_norm(b.get("instructor"))) or ins_by_batch.get(b["batch"])
        if ins_code and ins_by_batch.get(b["batch"]) and ins_code != ins_by_batch[b["batch"]]:
            warnings.append(f"Batch {b['batch']}: batches and instructors collections disagree on instructor")
        batches.append({
            "batch_code": b["batch"],
            "course_code": course_code(b.get("course")),
            "instructor_code": ins_code,
            "schedule": b.get("schedule"),
            "status": b.get("status", "Active"),
            "engagement_score": engagement.get(b["batch"]),
            "created_at": now,
        })
    known_batches = {b["batch_code"] for b in batches}
    # batches listed only inside `course` documents
    for c in old.get("course", []):
        for bc in c.get("batches", []):
            if bc not in known_batches:
                batches.append({"batch_code": bc, "course_code": c["course_code"], "instructor_code": ins_by_batch.get(bc),
                                "schedule": None, "status": "Active", "engagement_score": None, "created_at": now})
                known_batches.add(bc)

    # ---- students -------------------------------------------------------
    students = []
    for s in sorted(old.get("students", []), key=lambda x: x["student_code"]):
        students.append({
            "student_code": s["student_code"],
            "name": s.get("student_name") or s.get("name"),
            "course_code": course_code(s.get("course")),
            "batch_code": s.get("batch"),
            "learning_progress": _num(s.get("learning_progress")) or 0,
            "email": s.get("email"),
            "phone": s.get("phone"),
            "created_at": now,
        })
    student_course = {s["student_code"]: s["course_code"] for s in students}

    # ---- marks ------------------------------------------------------------
    marks = []
    for m in sorted(old.get("marks", []), key=lambda x: x["student_code"]):
        code = m["student_code"]
        value = _num(m.get("marks"))
        marks.append({
            "student_code": code,
            "course_code": course_code(m.get("course")) or student_course.get(code),
            "marks": value,
            "max_marks": 100,
            "assessments": [],
            "updated_at": now,
        })
        expected = "Pass" if value is not None and value >= default_pass_mark else "Fail"
        if m.get("result") and m["result"] != expected:
            warnings.append(f"{code}: stored result '{m['result']}' differs from computed '{expected}' (pass mark {default_pass_mark})")

    # ---- attendance -----------------------------------------------------
    attendance = []
    for a in sorted(old.get("attendance", []), key=lambda x: x["student_code"]):
        total, attended = _num(a.get("total_classes")), _num(a.get("classes_attended"))
        attendance.append({
            "student_code": a["student_code"],
            "course_code": course_code(a.get("course")) or student_course.get(a["student_code"]),
            "total_classes": total,
            "classes_attended": attended,
            "updated_at": now,
        })
        if total and attended is not None and a.get("attendance_percentage") is not None:
            if round(attended / total * 100) != a["attendance_percentage"]:
                warnings.append(
                    f"{a['student_code']}: stored attendance {a['attendance_percentage']}% replaced by computed "
                    f"{round(attended / total * 100, 1)}% ({attended}/{total})"
                )

    # ---- admins ---------------------------------------------------------
    admins = [{
        "admin_code": a.get("admin_id") or a.get("admin_code"),
        "name": a["name"],
        "email": a.get("email"),
        "phone": a.get("phone"),
        "created_at": now,
    } for a in sorted(old.get("admins", []), key=lambda x: x.get("admin_id") or x.get("admin_code"))]

    # ---- counters (next IDs) ----------------------------------------------
    def max_seq(codes, prefix):
        nums = [int(c[len(prefix):]) for c in codes if c and c.startswith(prefix) and c[len(prefix):].isdigit()]
        return max(nums, default=0)

    counters = [
        {"_id": "student", "prefix": "STD", "seq": max_seq([s["student_code"] for s in students], "STD")},
        {"_id": "instructor", "prefix": "INS", "seq": max_seq([i["instructor_code"] for i in instructors], "INS")},
        {"_id": "admin", "prefix": "ADM", "seq": max_seq([a["admin_code"] for a in admins], "ADM")},
        {"_id": "course", "prefix": "C", "seq": max_seq([c["course_code"] for c in courses], "C")},
    ]

    return {
        "courses": courses,
        "batches": batches,
        "students": students,
        "instructors": instructors,
        "admins": admins,
        "marks": marks,
        "attendance": attendance,
        "counters": counters,
        "warnings": warnings,
    }


INDEXES = {
    "users": [("user_id", True)],
    "students": [("student_code", True), ("batch_code", False)],
    "instructors": [("instructor_code", True)],
    "admins": [("admin_code", True)],
    "courses": [("course_code", True)],
    "batches": [("batch_code", True), ("instructor_code", False)],
    "marks": [("student_code", False)],
    "attendance": [("student_code", False)],
    "pending_actions": [("action_id", True)],
}


def ensure_indexes(db):
    for col, specs in INDEXES.items():
        for field, unique in specs:
            db[col].create_index(field, unique=unique)
