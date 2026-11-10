"""Read side of the LMS: joins the normalised collections into ready-to-use rows
and computes statistics in Python so the language model never does arithmetic."""
from statistics import mean

from app.config import settings

P = {"_id": 0}


class Directory:
    def __init__(self, db):
        self.db = db

    # ---- raw lookups ------------------------------------------------------
    def courses(self):
        return list(self.db["courses"].find({}, P).sort("course_code", 1))

    def course(self, code):
        return self.db["courses"].find_one({"course_code": code}, P)

    def batches(self, flt=None):
        return list(self.db["batches"].find(flt or {}, P).sort("batch_code", 1))

    def batch(self, code):
        return self.db["batches"].find_one({"batch_code": code}, P)

    def instructors(self):
        return list(self.db["instructors"].find({}, P).sort("instructor_code", 1))

    def instructor(self, code):
        return self.db["instructors"].find_one({"instructor_code": code}, P)

    def admins(self):
        return list(self.db["admins"].find({}, P).sort("admin_code", 1))

    def admin(self, code):
        return self.db["admins"].find_one({"admin_code": code}, P)

    def student(self, code):
        return self.db["students"].find_one({"student_code": code}, P)

    def user(self, user_id):
        return self.db["users"].find_one({"user_id": user_id}, P)

    def profile(self, user_id, role):
        if role == "student":
            return self.student(user_id)
        if role == "instructor":
            return self.instructor(user_id)
        if role == "admin":
            return self.admin(user_id)
        return None

    def login_ids(self):
        return {u["user_id"] for u in self.db["users"].find({"active": True}, {"_id": 0, "user_id": 1})}

    # ---- joined student rows ----------------------------------------------
    def student_rows(self, flt=None):
        students = list(self.db["students"].find(flt or {}, P).sort("student_code", 1))
        if not students:
            return []
        codes = [s["student_code"] for s in students]
        courses = {c["course_code"]: c for c in self.courses()}
        batches = {b["batch_code"]: b for b in self.batches()}
        instructors = {i["instructor_code"]: i for i in self.instructors()}
        marks = {(m["student_code"], m.get("course_code")): m for m in self.db["marks"].find({"student_code": {"$in": codes}}, P)}
        att = {(a["student_code"], a.get("course_code")): a for a in self.db["attendance"].find({"student_code": {"$in": codes}}, P)}
        logins = self.login_ids()

        rows = []
        for s in students:
            course = courses.get(s.get("course_code"), {})
            batch = batches.get(s.get("batch_code"), {})
            ins = instructors.get(batch.get("instructor_code"), {})
            m = marks.get((s["student_code"], s.get("course_code"))) or {}
            a = att.get((s["student_code"], s.get("course_code"))) or {}
            pass_mark = course.get("pass_mark", settings.DEFAULT_PASS_MARK)
            score = m.get("marks")
            total, attended = a.get("total_classes"), a.get("classes_attended")
            rows.append({
                "student_code": s["student_code"],
                "name": s.get("name"),
                "course_code": s.get("course_code"),
                "course_name": course.get("name"),
                "batch_code": s.get("batch_code"),
                "batch_status": batch.get("status"),
                "schedule": batch.get("schedule"),
                "instructor_code": batch.get("instructor_code"),
                "instructor_name": ins.get("name"),
                "instructor_email": ins.get("email"),
                "learning_progress": s.get("learning_progress"),
                "marks": score,
                "max_marks": m.get("max_marks", course.get("max_marks", 100)),
                "pass_mark": pass_mark,
                "result": None if score is None else ("Pass" if score >= pass_mark else "Fail"),
                "assessments": m.get("assessments", []),
                "classes_attended": attended,
                "total_classes": total,
                "attendance_pct": round(attended / total * 100, 1) if total else None,
                "email": s.get("email"),
                "phone": s.get("phone"),
                "has_login": s["student_code"] in logins,
            })
        return rows

    def student_row(self, code):
        rows = self.student_rows({"student_code": code})
        return rows[0] if rows else None

    def instructor_batches(self, instructor_code):
        return self.batches({"instructor_code": instructor_code})

    def instructor_student_rows(self, instructor_code):
        codes = [b["batch_code"] for b in self.instructor_batches(instructor_code)]
        return self.student_rows({"batch_code": {"$in": codes}}) if codes else []


def summarize(rows):
    """Aggregate statistics for a group of joined student rows."""
    scored = [r for r in rows if r["marks"] is not None]
    attended = [r for r in rows if r["attendance_pct"] is not None]
    low_att = settings.LOW_ATTENDANCE

    def r1(x):
        return round(x, 1) if x is not None else None

    by_marks = sorted(scored, key=lambda r: r["marks"], reverse=True)
    return {
        "students": len(rows),
        "average_marks": r1(mean(r["marks"] for r in scored)) if scored else None,
        "highest": {"name": by_marks[0]["name"], "code": by_marks[0]["student_code"], "marks": by_marks[0]["marks"]} if by_marks else None,
        "lowest": {"name": by_marks[-1]["name"], "code": by_marks[-1]["student_code"], "marks": by_marks[-1]["marks"]} if by_marks else None,
        "passed": sum(1 for r in scored if r["result"] == "Pass"),
        "failed": sum(1 for r in scored if r["result"] == "Fail"),
        "pass_rate": r1(100 * sum(1 for r in scored if r["result"] == "Pass") / len(scored)) if scored else None,
        "average_attendance": r1(mean(r["attendance_pct"] for r in attended)) if attended else None,
        "average_progress": r1(mean(r["learning_progress"] for r in rows if r["learning_progress"] is not None)) if rows else None,
        "failing_students": [f"{r['name']} ({r['student_code']}, {r['marks']})" for r in scored if r["result"] == "Fail"],
        "low_attendance_students": [
            f"{r['name']} ({r['student_code']}, {r['attendance_pct']}%)" for r in attended if r["attendance_pct"] < low_att
        ],
        "low_attendance_threshold": low_att,
    }


def group_stats(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(r.get(key), []).append(r)
    return {k: summarize(v) for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))}
