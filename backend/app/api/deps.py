from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.db import get_db
from app.core.security import decode_token
from app.services.directory import Directory

bearer = HTTPBearer(auto_error=False)


def db_dep():
    return get_db()


def current_user(creds: HTTPAuthorizationCredentials = Depends(bearer), db=Depends(db_dep)) -> dict:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        payload = decode_token(creds.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please sign in again")
    d = Directory(db)
    account = d.user(payload["sub"])
    if not account or not account.get("active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is disabled or no longer exists")
    profile = d.profile(account["user_id"], account["role"]) or {}
    return {"user_id": account["user_id"], "role": account["role"], "name": profile.get("name", account["user_id"]),
            "must_change_password": account.get("must_change_password", False)}


def require(*roles):
    def checker(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to this")
        return user
    return checker
