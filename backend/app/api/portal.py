"""Read-only data behind the dashboard 'Explore' pages."""
from fastapi import APIRouter, Depends

from app.api.deps import db_dep, require
from app.config import settings
from app.services.directory import Directory, group_stats, summarize

router = APIRouter(prefix="/api", tags=["portal"])


@router.get("/student/overview")
def student_overview(user=Depends(require("student")), db=Depends(db_dep)):
    row = Directory(db).student_row(user["user_id"])
    return {"record": row, "low_attendance_threshold": settings.LOW_ATTENDANCE}


@router.get("/instructor/class")
def instructor_class(user=Depends(require("instructor")), db=Depends(db_dep)):
    d = Directory(db)
    batches = d.instructor_batches(user["user_id"])
    rows = d.instructor_student_rows(user["user_id"])
    courses = {c["course_code"]: c["name"] for c in d.courses()}
    for r in rows:
        r.pop("email", None)
        r.pop("phone", None)
    return {
        "batches": [{**b, "course_name": courses.get(b["course_code"])} for b in batches],
        "students": rows,
        "summary": summarize(rows),
        "by_batch": group_stats(rows, "batch_code"),
        "low_attendance_threshold": settings.LOW_ATTENDANCE,
    }


@router.get("/admin/overview")
def admin_overview(user=Depends(require("admin")), db=Depends(db_dep)):
    d = Directory(db)
    rows = d.student_rows()
    batches = d.batches()
    courses = d.courses()
    instructors = {i["instructor_code"]: i["name"] for i in d.instructors()}
    cname = {c["course_code"]: c["name"] for c in courses}
    bstats = group_stats(rows, "batch_code")
    cstats = group_stats(rows, "course_code")
    return {
        "totals": {"students": len(rows), "instructors": len(instructors), "admins": len(d.admins()),
                   "courses": len(courses), "batches": len(batches),
                   "active_batches": sum(1 for b in batches if b.get("status") == "Active"),
                   "logins": len(d.login_ids())},
        "summary": summarize(rows),
        "courses": [{**c, "stats": cstats.get(c["course_code"])} for c in courses],
        "batches": [{**b, "course_name": cname.get(b["course_code"]), "instructor_name": instructors.get(b.get("instructor_code")),
                     "stats": bstats.get(b["batch_code"])} for b in batches],
        "low_attendance_threshold": settings.LOW_ATTENDANCE,
    }
