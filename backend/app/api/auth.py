from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import current_user, db_dep
from app.core.ledger import Ledger
from app.core.security import create_token, hash_password, verify_password
from app.services.directory import Directory

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=200)


@router.post("/login")
def login(body: LoginIn, db=Depends(db_dep)):
    uid = body.user_id.strip().upper()
    d = Directory(db)
    account = d.user(uid)
    if not account or not verify_password(body.password, account.get("password_hash", "")):
        raise HTTPException(401, "Incorrect user ID or password")
    if not account.get("active", True):
        raise HTTPException(403, "This account is disabled. Please contact the admin.")
    profile = d.profile(uid, account["role"]) or {}
    db["users"].update_one({"user_id": uid}, {"$set": {"last_login": datetime.now(timezone.utc).isoformat(timespec="seconds")}})
    return {
        "token": create_token(uid, account["role"]),
        "user": {"user_id": uid, "role": account["role"], "name": profile.get("name", uid),
                 "must_change_password": account.get("must_change_password", False)},
    }


@router.get("/me")
def me(user=Depends(current_user)):
    return user


@router.post("/change-password")
def change_password(body: ChangePasswordIn, user=Depends(current_user), db=Depends(db_dep)):
    account = Directory(db).user(user["user_id"])
    if not verify_password(body.current_password, account["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    db["users"].update_one({"user_id": user["user_id"]},
                           {"$set": {"password_hash": hash_password(body.new_password), "must_change_password": False}})
    Ledger(db).append(user, "change_own_password", user["user_id"], {})
    return {"ok": True}
