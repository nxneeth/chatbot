"""Admin management: users, courses, batches, CSV import and the audit ledger.
All writes go through services.actions, so they are validated and logged."""
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import db_dep, require
from app.core.ledger import Ledger
from app.services.actions import ACTION_TYPES, ActionError, Actions
from app.services.directory import Directory

router = APIRouter(prefix="/api/admin", tags=["admin"])
admin_only = require("admin")


class ActionIn(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ImportIn(BaseModel):
    role: Literal["student", "instructor"]
    csv: str = Field(max_length=500_000)
    dry_run: bool = False


@router.get("/users")
def users(role: Literal["student", "instructor", "admin"] = "student", user=Depends(admin_only), db=Depends(db_dep)):
    d = Directory(db)
    accounts = {u["user_id"]: u for u in db["users"].find({}, {"_id": 0, "password_hash": 0})}

    def login_info(uid):
        a = accounts.get(uid)
        return {"has_login": bool(a), "active": bool(a and a.get("active", True)), "last_login": a.get("last_login") if a else None}

    if role == "student":
        return [{**r, **login_info(r["student_code"])} for r in d.student_rows()]
    if role == "instructor":
        out = []
        for i in d.instructors():
            out.append({**i, "batches": [b["batch_code"] for b in d.instructor_batches(i["instructor_code"])],
                        **login_info(i["instructor_code"])})
        return out
    return [{**a, **login_info(a["admin_code"])} for a in d.admins()]


@router.get("/courses")
def courses(user=Depends(admin_only), db=Depends(db_dep)):
    return Directory(db).courses()


@router.get("/batches")
def batches(user=Depends(admin_only), db=Depends(db_dep)):
    d = Directory(db)
    return [{**b, "students": db["students"].count_documents({"batch_code": b["batch_code"]})} for b in d.batches()]


@router.post("/actions/preview")
def preview(body: ActionIn, user=Depends(admin_only), db=Depends(db_dep)):
    if body.type not in ACTION_TYPES:
        raise HTTPException(400, f"Unknown action {body.type}")
    try:
        return Actions(db).validate(body.model_dump(), user)
    except ActionError as e:
        raise HTTPException(400, str(e))


@router.post("/actions")
def run_action(body: ActionIn, user=Depends(admin_only), db=Depends(db_dep)):
    if body.type not in ACTION_TYPES:
        raise HTTPException(400, f"Unknown action {body.type}")
    try:
        return Actions(db).execute(body.model_dump(), user)
    except ActionError as e:
        raise HTTPException(400, str(e))


@router.post("/import")
def bulk_import(body: ImportIn, user=Depends(admin_only), db=Depends(db_dep)):
    try:
        return Actions(db).bulk_import(body.csv, body.role, user, dry_run=body.dry_run)
    except ActionError as e:
        raise HTTPException(400, str(e))


@router.get("/ledger")
def ledger(limit: int = 50, skip: int = 0, user=Depends(admin_only), db=Depends(db_dep)):
    led = Ledger(db)
    return {"blocks": led.list(limit=min(limit, 200), skip=skip), "total": db["audit_ledger"].count_documents({})}


@router.get("/ledger/verify")
def ledger_verify(user=Depends(admin_only), db=Depends(db_dep)):
    return Ledger(db).verify()


@router.get("/ledger/checkpoints")
def ledger_checkpoints(user=Depends(admin_only), db=Depends(db_dep)):
    return Ledger(db).list_checkpoints()


@router.post("/ledger/checkpoints")
def ledger_checkpoint(user=Depends(admin_only), db=Depends(db_dep)):
    try:
        return Ledger(db).create_checkpoint(user)
    except ValueError as e:
        raise HTTPException(409, str(e))
