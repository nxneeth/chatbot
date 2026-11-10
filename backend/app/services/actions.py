"""Write side of the LMS. Every change, whether it comes from the admin panel or
from the chatbot, goes through validate() then execute(), and every executed
action is appended to the audit ledger."""
import csv
import io
import re
from datetime import datetime, timezone

from app.config import settings
from app.core.ledger import Ledger
from app.core.security import hash_password, temporary_password
from app.services.directory import Directory

P = {"_id": 0}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PROFILE_COLLECTION = {"student": ("students", "student_code"), "instructor": ("instructors", "instructor_code"),
                      "admin": ("admins", "admin_code")}
ROLE_BY_PREFIX = {"STD": "student", "INS": "instructor", "ADM": "admin"}

ACTION_TYPES = {
    "create_user", "update_user", "delete_user", "reset_password",
    "create_course", "update_course", "delete_course",
    "create_batch", "update_batch", "delete_batch",
    "assign_instructor", "enroll_student", "record_marks", "record_attendance",
}
DESTRUCTIVE = {"delete_user", "delete_course", "delete_batch"}


class ActionError(ValueError):
    """Raised with a message that can be shown to the admin as-is."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(s):
    return s.strip() if isinstance(s, str) else s


def _num(value, field, lo=None, hi=None, integer=False):
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ActionError(f"{field} must be a number")
    if integer and not n.is_integer():
        raise ActionError(f"{field} must be a whole number")
    if lo is not None and n < lo or hi is not None and n > hi:
        raise ActionError(f"{field} must be between {lo} and {hi}")
    return int(n) if n.is_integer() else n


class Actions:
    def __init__(self, db):
        self.db = db
        self.dir = Directory(db)
        self.ledger = Ledger(db)

    # ------------------------------------------------------------------ helpers
    def _role_of(self, user_id):
        role = ROLE_BY_PREFIX.get((user_id or "")[:3].upper())
        if not role:
            raise ActionError(f"'{user_id}' is not a valid user ID (expected STD###, INS### or ADM###)")
        return role

    def _profile(self, user_id):
        role = self._role_of(user_id)
        col, key = PROFILE_COLLECTION[role]
        doc = self.db[col].find_one({key: user_id}, P)
        if not doc:
            raise ActionError(f"No {role} with ID {user_id}")
        return role, doc

    def _course_code(self, value, required=True):
        value = _clean(value)
        if not value:
            if required:
                raise ActionError("A course is required")
            return None
        norm = re.sub(r"[^a-z0-9]", "", value.lower())
        for c in self.dir.courses():
            names = [c["course_code"], c["name"], *c.get("aliases", [])]
            if norm in {re.sub(r"[^a-z0-9]", "", n.lower()) for n in names}:
                return c["course_code"]
        raise ActionError(f"Unknown course '{value}'. Existing courses: " + ", ".join(c["name"] for c in self.dir.courses()))

    def _batch(self, code):
        code = (_clean(code) or "").upper()
        if not code:
            raise ActionError("A batch is required")
        b = self.dir.batch(code)
        if not b:
            raise ActionError(f"Unknown batch '{code}'. Existing batches: " + ", ".join(x["batch_code"] for x in self.dir.batches()))
        return b

    def _instructor_code(self, value):
        value = _clean(value)
        if not value:
            return None
        if value.upper().startswith("INS"):
            if not self.dir.instructor(value.upper()):
                raise ActionError(f"No instructor with ID {value.upper()}")
            return value.upper()
        matches = [i for i in self.dir.instructors() if value.lower() in i["name"].lower()]
        if len(matches) != 1:
            raise ActionError(f"Could not identify instructor '{value}'" + (" (more than one match)" if matches else ""))
        return matches[0]["instructor_code"]

    def _next_id(self, kind):
        doc = self.db["counters"].find_one_and_update({"_id": kind}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
        prefix = {"student": "STD", "instructor": "INS", "admin": "ADM", "course": "C"}[kind]
        return f"{prefix}{doc['seq']:03d}"

    def _email(self, value):
        value = _clean(value)
        if value and not EMAIL_RE.match(value):
            raise ActionError(f"'{value}' is not a valid email address")
        return value or None

    # --------------------------------------------------------------- validate
    def validate(self, action: dict, actor: dict) -> dict:
        """Check an action and return {action, summary, destructive}. Raises ActionError."""
        if not isinstance(action, dict):
            raise ActionError("Malformed action")
        t = action.get("type")
        p = dict(action.get("payload") or {})
        if t not in ACTION_TYPES:
            raise ActionError(f"Unsupported action '{t}'")
        fn = getattr(self, f"_v_{t}")
        payload, summary = fn(p, actor)
        return {"action": {"type": t, "payload": payload}, "summary": summary, "destructive": t in DESTRUCTIVE}

    def _v_create_user(self, p, actor):
        role = (p.get("role") or "").lower().strip()
        if role == "teacher":
            role = "instructor"
        if role not in PROFILE_COLLECTION:
            raise ActionError("Role must be student, instructor or admin")
        name = _clean(p.get("name"))
        if not name:
            raise ActionError("A name is required")
        out = {"role": role, "name": name, "email": self._email(p.get("email")), "phone": _clean(p.get("phone")) or None,
               "create_login": p.get("create_login", True) is not False}
        if p.get("password"):
            if len(str(p["password"])) < 6:
                raise ActionError("Password must be at least 6 characters")
            out["password"] = str(p["password"])
        lines = [f"Add a new {role}: {name}"]
        if role == "student":
            batch = self._batch(p.get("batch_code") or p.get("batch"))
            if p.get("course") or p.get("course_code"):
                cc = self._course_code(p.get("course_code") or p.get("course"))
                if cc != batch["course_code"]:
                    raise ActionError(f"Batch {batch['batch_code']} belongs to {self.dir.course(batch['course_code'])['name']}, not that course")
            out["batch_code"] = batch["batch_code"]
            out["learning_progress"] = _num(p.get("learning_progress", 0), "Learning progress", 0, 100)
            lines.append(f"Course {self.dir.course(batch['course_code'])['name']}, batch {batch['batch_code']}")
        if role == "instructor":
            codes = p.get("batch_codes") or ([p["batch_code"]] if p.get("batch_code") else [])
            out["batch_codes"] = [self._batch(c)["batch_code"] for c in codes]
            if out["batch_codes"]:
                lines.append("Teaches batch " + ", ".join(out["batch_codes"]))
        if out["email"]:
            lines.append(f"Email {out['email']}")
        lines.append("Login: " + ("yes, with the password given" if out.get("password") else "yes, with a temporary password")
                     if out["create_login"] else "Login: no (record only)")
        lines.append("A new ID will be assigned automatically")
        return out, lines

    def _v_update_user(self, p, actor):
        uid = (_clean(p.get("user_id")) or "").upper()
        role, doc = self._profile(uid)
        fields = dict(p.get("fields") or {k: v for k, v in p.items() if k != "user_id"})
        allowed = {"name", "email", "phone", "active"} | ({"batch_code", "learning_progress"} if role == "student" else set())
        bad = set(fields) - allowed
        if bad:
            raise ActionError(f"Cannot change {', '.join(sorted(bad))} for a {role}")
        if not fields:
            raise ActionError("Nothing to change")
        out, lines = {}, [f"Update {doc['name']} ({uid})"]
        for k, v in fields.items():
            if k == "email":
                v = self._email(v)
            elif k == "batch_code":
                v = self._batch(v)["batch_code"]
            elif k == "learning_progress":
                v = _num(v, "Learning progress", 0, 100)
            elif k == "active":
                v = bool(v)
                if not v and uid == actor.get("user_id"):
                    raise ActionError("You cannot disable your own login")
            elif k == "name":
                v = _clean(v)
                if not v:
                    raise ActionError("Name cannot be empty")
            out[k] = v
            lines.append(f"{k.replace('_', ' ')}: {(doc.get(k) if doc.get(k) is not None else '—') if k != 'active' else 'login'} → {v if k != 'active' else ('enabled' if v else 'disabled')}")
        return {"user_id": uid, "fields": out}, lines

    def _v_delete_user(self, p, actor):
        uid = (_clean(p.get("user_id")) or "").upper()
        role, doc = self._profile(uid)
        if uid == actor.get("user_id"):
            raise ActionError("You cannot delete your own account")
        if role == "admin" and self.db["admins"].count_documents({}) <= 1:
            raise ActionError("Cannot delete the last admin")
        lines = [f"Permanently remove {role} {doc['name']} ({uid}) and their login"]
        if role == "student":
            lines.append("Their marks and attendance records will also be removed")
        if role == "instructor":
            b = [x["batch_code"] for x in self.dir.instructor_batches(uid)]
            if b:
                lines.append(f"Batches {', '.join(b)} will be left without an instructor")
        return {"user_id": uid}, lines

    def _v_reset_password(self, p, actor):
        uid = (_clean(p.get("user_id")) or "").upper()
        role, doc = self._profile(uid)
        out = {"user_id": uid}
        if p.get("new_password") or p.get("password"):
            pw = str(p.get("new_password") or p.get("password"))
            if len(pw) < 6:
                raise ActionError("Password must be at least 6 characters")
            out["new_password"] = pw
        has_login = self.dir.user(uid) is not None
        verb = "Reset the password for" if has_login else "Create a login for"
        return out, [f"{verb} {doc['name']} ({uid})",
                     "Using the password given" if "new_password" in out else "A temporary password will be generated and shown once"]

    def _v_create_course(self, p, actor):
        name = _clean(p.get("name"))
        if not name:
            raise ActionError("A course name is required")
        try:
            self._course_code(name)
            raise ActionError(f"A course called '{name}' already exists")
        except ActionError as e:
            if "already exists" in str(e):
                raise
        out = {"name": name, "pass_mark": _num(p.get("pass_mark", settings.DEFAULT_PASS_MARK), "Pass mark", 0, 1000),
               "max_marks": _num(p.get("max_marks", 100), "Max marks", 1, 1000), "aliases": p.get("aliases") or []}
        if out["pass_mark"] > out["max_marks"]:
            raise ActionError("Pass mark cannot exceed max marks")
        return out, [f"Create course {name}", f"Pass mark {out['pass_mark']} out of {out['max_marks']}"]

    def _v_update_course(self, p, actor):
        code = self._course_code(p.get("course_code") or p.get("course"))
        course = self.dir.course(code)
        fields = dict(p.get("fields") or {k: v for k, v in p.items() if k not in ("course_code", "course")})
        out = {}
        for k, v in fields.items():
            if k == "name":
                out[k] = _clean(v)
            elif k in ("pass_mark", "max_marks"):
                out[k] = _num(v, k.replace("_", " "), 0, 1000)
            elif k == "aliases":
                out[k] = list(v)
            else:
                raise ActionError(f"Cannot change {k} on a course")
        if not out:
            raise ActionError("Nothing to change")
        return {"course_code": code, "fields": out}, [f"Update course {course['name']} ({code})"] + [f"{k}: {course.get(k)} → {v}" for k, v in out.items()]

    def _v_delete_course(self, p, actor):
        code = self._course_code(p.get("course_code") or p.get("course"))
        if self.dir.batches({"course_code": code}):
            raise ActionError("This course still has batches. Delete or move them first.")
        return {"course_code": code}, [f"Permanently remove course {self.dir.course(code)['name']} ({code})"]

    def _v_create_batch(self, p, actor):
        code = (_clean(p.get("batch_code")) or "").upper()
        if not re.fullmatch(r"[A-Z0-9-]{1,12}", code):
            raise ActionError("Batch code must be short letters/numbers, e.g. A4")
        if self.dir.batch(code):
            raise ActionError(f"Batch {code} already exists")
        course = self._course_code(p.get("course_code") or p.get("course"))
        out = {"batch_code": code, "course_code": course, "instructor_code": self._instructor_code(p.get("instructor_code") or p.get("instructor")),
               "schedule": _clean(p.get("schedule")) or None, "status": _clean(p.get("status")) or "Active"}
        return out, [f"Create batch {code} for {self.dir.course(course)['name']}",
                     f"Instructor: {self.dir.instructor(out['instructor_code'])['name'] if out['instructor_code'] else 'none yet'}",
                     f"Schedule: {out['schedule'] or 'not set'}"]

    def _v_update_batch(self, p, actor):
        batch = self._batch(p.get("batch_code"))
        fields = dict(p.get("fields") or {k: v for k, v in p.items() if k != "batch_code"})
        out = {}
        for k, v in fields.items():
            if k in ("schedule", "status"):
                out[k] = _clean(v)
            elif k in ("instructor_code", "instructor"):
                out["instructor_code"] = self._instructor_code(v)
            else:
                raise ActionError(f"Cannot change {k} on a batch")
        if not out:
            raise ActionError("Nothing to change")
        return {"batch_code": batch["batch_code"], "fields": out}, [f"Update batch {batch['batch_code']}"] + [f"{k}: {batch.get(k)} → {v}" for k, v in out.items()]

    def _v_delete_batch(self, p, actor):
        batch = self._batch(p.get("batch_code"))
        n = self.db["students"].count_documents({"batch_code": batch["batch_code"]})
        if n:
            raise ActionError(f"Batch {batch['batch_code']} still has {n} students. Move them first.")
        return {"batch_code": batch["batch_code"]}, [f"Permanently remove batch {batch['batch_code']}"]

    def _v_assign_instructor(self, p, actor):
        ins = self._instructor_code(p.get("instructor_code") or p.get("instructor"))
        if not ins:
            raise ActionError("An instructor is required")
        batch = self._batch(p.get("batch_code"))
        old = self.dir.instructor(batch.get("instructor_code")) if batch.get("instructor_code") else None
        return {"instructor_code": ins, "batch_code": batch["batch_code"]}, [
            f"Assign {self.dir.instructor(ins)['name']} ({ins}) to batch {batch['batch_code']}",
            f"Replaces {old['name']}" if old else "Batch currently has no instructor"]

    def _v_enroll_student(self, p, actor):
        uid = (_clean(p.get("student_code") or p.get("user_id")) or "").upper()
        role, doc = self._profile(uid)
        if role != "student":
            raise ActionError(f"{uid} is not a student")
        batch = self._batch(p.get("batch_code"))
        lines = [f"Move {doc['name']} ({uid}) from batch {doc.get('batch_code')} to {batch['batch_code']}"]
        if batch["course_code"] != doc.get("course_code"):
            lines.append(f"Course changes to {self.dir.course(batch['course_code'])['name']}; existing marks stay under the old course")
        return {"student_code": uid, "batch_code": batch["batch_code"]}, lines

    def _v_record_marks(self, p, actor):
        uid = (_clean(p.get("student_code") or p.get("user_id")) or "").upper()
        role, doc = self._profile(uid)
        if role != "student":
            raise ActionError(f"{uid} is not a student")
        course = self.dir.course(doc["course_code"])
        out = {"student_code": uid, "course_code": doc["course_code"]}
        if p.get("assessment"):
            a = p["assessment"]
            name = _clean(a.get("name"))
            if not name:
                raise ActionError("Assessment name is required")
            mx = _num(a.get("max", 100), "Assessment max", 1, 1000)
            out["assessment"] = {"name": name, "score": _num(a.get("score"), "Score", 0, mx), "max": mx}
            return out, [f"Record {name} for {doc['name']} ({uid}): {out['assessment']['score']}/{mx}"]
        out["marks"] = _num(p.get("marks"), "Marks", 0, course.get("max_marks", 100))
        current = self.db["marks"].find_one({"student_code": uid, "course_code": doc["course_code"]}, P)
        return out, [f"Set {course['name']} marks for {doc['name']} ({uid}) to {out['marks']}/{course.get('max_marks', 100)}",
                     f"Currently {current['marks']}" if current else "No marks recorded yet"]

    def _v_record_attendance(self, p, actor):
        uid = (_clean(p.get("student_code") or p.get("user_id")) or "").upper()
        role, doc = self._profile(uid)
        if role != "student":
            raise ActionError(f"{uid} is not a student")
        total = _num(p.get("total_classes"), "Total classes", 0, 10000, integer=True)
        attended = _num(p.get("classes_attended"), "Classes attended", 0, total, integer=True)
        pct = round(attended / total * 100, 1) if total else 0
        return {"student_code": uid, "course_code": doc["course_code"], "total_classes": total, "classes_attended": attended}, [
            f"Set attendance for {doc['name']} ({uid}) to {attended} of {total} classes ({pct}%)"]

    # ---------------------------------------------------------------- execute
    def execute(self, action: dict, actor: dict) -> dict:
        checked = self.validate(action, actor)  # always re-validate at execution time
        t, p = checked["action"]["type"], checked["action"]["payload"]
        result = getattr(self, f"_x_{t}")(p, actor)
        details = {k: v for k, v in p.items()}
        details.update({k: v for k, v in result.get("data", {}).items() if k != "temporary_password"})
        self.ledger.append(actor, t, result.get("target"), details)
        return result

    def _x_create_user(self, p, actor):
        role = p["role"]
        uid = self._next_id(role)
        col, key = PROFILE_COLLECTION[role]
        doc = {key: uid, "name": p["name"], "email": p.get("email"), "phone": p.get("phone"), "created_at": _now()}
        if role == "student":
            batch = self.dir.batch(p["batch_code"])
            doc.update({"course_code": batch["course_code"], "batch_code": p["batch_code"], "learning_progress": p.get("learning_progress", 0)})
        self.db[col].insert_one(doc)
        if role == "instructor":
            for b in p.get("batch_codes", []):
                self.db["batches"].update_one({"batch_code": b}, {"$set": {"instructor_code": uid}})
        data = {"user_id": uid}
        msg = f"{p['name']} was added as {role} {uid}."
        if p.get("create_login", True):
            pw = p.get("password") or temporary_password()
            self.db["users"].insert_one({"user_id": uid, "role": role, "password_hash": hash_password(pw), "active": True,
                                         "must_change_password": "password" not in p, "created_at": _now()})
            if "password" not in p:
                data["temporary_password"] = pw
            else:
                msg += " They can sign in with the password you set."
        return {"ok": True, "message": msg, "target": uid, "data": data}

    def _x_update_user(self, p, actor):
        uid, fields = p["user_id"], dict(p["fields"])
        role = self._role_of(uid)
        col, key = PROFILE_COLLECTION[role]
        if "active" in fields:
            self.db["users"].update_one({"user_id": uid}, {"$set": {"active": fields.pop("active")}})
        if "batch_code" in fields:
            fields["course_code"] = self.dir.batch(fields["batch_code"])["course_code"]
        if fields:
            self.db[col].update_one({key: uid}, {"$set": fields})
        return {"ok": True, "message": f"{uid} was updated.", "target": uid}

    def _x_delete_user(self, p, actor):
        uid = p["user_id"]
        role = self._role_of(uid)
        col, key = PROFILE_COLLECTION[role]
        self.db[col].delete_one({key: uid})
        self.db["users"].delete_one({"user_id": uid})
        if role == "student":
            self.db["marks"].delete_many({"student_code": uid})
            self.db["attendance"].delete_many({"student_code": uid})
        if role == "instructor":
            self.db["batches"].update_many({"instructor_code": uid}, {"$set": {"instructor_code": None}})
        return {"ok": True, "message": f"{uid} was removed.", "target": uid}

    def _x_reset_password(self, p, actor):
        uid = p["user_id"]
        pw = p.get("new_password") or temporary_password()
        existed = self.dir.user(uid) is not None
        self.db["users"].update_one({"user_id": uid}, {
            "$set": {"user_id": uid, "role": self._role_of(uid), "password_hash": hash_password(pw), "active": True,
                     "must_change_password": "new_password" not in p, "updated_at": _now()}}, upsert=True)
        data = {}
        msg = f"{'Password reset' if existed else 'Login created'} for {uid}."
        if "new_password" not in p:
            data["temporary_password"] = pw
        return {"ok": True, "message": msg, "target": uid, "data": data}

    def _x_create_course(self, p, actor):
        code = self._next_id("course")
        self.db["courses"].insert_one({"course_code": code, "name": p["name"], "aliases": sorted({p["name"], *p["aliases"]}),
                                       "pass_mark": p["pass_mark"], "max_marks": p["max_marks"], "created_at": _now()})
        return {"ok": True, "message": f"Course {p['name']} created as {code}.", "target": code, "data": {"course_code": code}}

    def _x_update_course(self, p, actor):
        self.db["courses"].update_one({"course_code": p["course_code"]}, {"$set": p["fields"]})
        return {"ok": True, "message": f"Course {p['course_code']} updated.", "target": p["course_code"]}

    def _x_delete_course(self, p, actor):
        self.db["courses"].delete_one({"course_code": p["course_code"]})
        return {"ok": True, "message": f"Course {p['course_code']} removed.", "target": p["course_code"]}

    def _x_create_batch(self, p, actor):
        self.db["batches"].insert_one({**p, "engagement_score": None, "created_at": _now()})
        return {"ok": True, "message": f"Batch {p['batch_code']} created.", "target": p["batch_code"]}

    def _x_update_batch(self, p, actor):
        self.db["batches"].update_one({"batch_code": p["batch_code"]}, {"$set": p["fields"]})
        return {"ok": True, "message": f"Batch {p['batch_code']} updated.", "target": p["batch_code"]}

    def _x_delete_batch(self, p, actor):
        self.db["batches"].delete_one({"batch_code": p["batch_code"]})
        return {"ok": True, "message": f"Batch {p['batch_code']} removed.", "target": p["batch_code"]}

    def _x_assign_instructor(self, p, actor):
        self.db["batches"].update_one({"batch_code": p["batch_code"]}, {"$set": {"instructor_code": p["instructor_code"]}})
        return {"ok": True, "message": f"{p['instructor_code']} now teaches batch {p['batch_code']}.", "target": p["batch_code"]}

    def _x_enroll_student(self, p, actor):
        batch = self.dir.batch(p["batch_code"])
        self.db["students"].update_one({"student_code": p["student_code"]},
                                       {"$set": {"batch_code": p["batch_code"], "course_code": batch["course_code"]}})
        return {"ok": True, "message": f"{p['student_code']} moved to batch {p['batch_code']}.", "target": p["student_code"]}

    def _x_record_marks(self, p, actor):
        key = {"student_code": p["student_code"], "course_code": p["course_code"]}
        course = self.dir.course(p["course_code"])
        existing = self.db["marks"].find_one(key, P)
        if not existing:
            self.db["marks"].insert_one({**key, "marks": None, "max_marks": course.get("max_marks", 100), "assessments": [], "updated_at": _now()})
        if "assessment" in p:
            self.db["marks"].update_one(key, {"$pull": {"assessments": {"name": p["assessment"]["name"]}}})
            self.db["marks"].update_one(key, {"$push": {"assessments": p["assessment"]}, "$set": {"updated_at": _now()}})
            msg = f"{p['assessment']['name']} recorded for {p['student_code']}."
        else:
            self.db["marks"].update_one(key, {"$set": {"marks": p["marks"], "updated_at": _now()}})
            msg = f"Marks for {p['student_code']} set to {p['marks']}."
        return {"ok": True, "message": msg, "target": p["student_code"]}

    def _x_record_attendance(self, p, actor):
        key = {"student_code": p["student_code"], "course_code": p["course_code"]}
        self.db["attendance"].update_one(key, {"$set": {"total_classes": p["total_classes"], "classes_attended": p["classes_attended"],
                                                        "updated_at": _now()}}, upsert=True)
        return {"ok": True, "message": f"Attendance for {p['student_code']} updated.", "target": p["student_code"]}

    # ------------------------------------------------------------ bulk import
    def bulk_import(self, csv_text: str, role: str, actor: dict, dry_run=False) -> dict:
        """CSV columns: name, email, phone, batch_code (students), password (optional)."""
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        if not reader.fieldnames or "name" not in [f.strip().lower() for f in reader.fieldnames]:
            raise ActionError("CSV must have a header row with at least a 'name' column")
        rows, errors = [], []
        for i, raw in enumerate(reader, start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            if not any(row.values()):
                continue
            payload = {"role": role, "name": row.get("name"), "email": row.get("email"), "phone": row.get("phone"),
                       "batch_code": row.get("batch_code") or row.get("batch")}
            if row.get("password"):
                payload["password"] = row["password"]
            try:
                self.validate({"type": "create_user", "payload": payload}, actor)
                rows.append(payload)
            except ActionError as e:
                errors.append({"line": i, "name": row.get("name"), "error": str(e)})
        if dry_run or errors:
            return {"ok": not errors, "valid": len(rows), "errors": errors, "created": []}
        created = []
        for payload in rows:
            r = self.execute({"type": "create_user", "payload": payload}, actor)
            created.append({"user_id": r["data"]["user_id"], "name": payload["name"],
                            "temporary_password": r["data"].get("temporary_password")})
        return {"ok": True, "valid": len(rows), "errors": [], "created": created}
