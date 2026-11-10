"""Database connection + first-time seeding shared by the app and scripts/migrate.py."""
import json
import logging
from datetime import datetime, timezone

from app.config import settings
from app.core.ledger import Ledger
from app.core.migration import NEW_COLLECTIONS, ensure_indexes, load_legacy_json, transform
from app.core.security import hash_password

log = logging.getLogger("edulayne.db")
_db = None

ROLE_BY_PREFIX = {"STD": "student", "INS": "instructor", "ADM": "admin"}


def role_for_user_id(user_id: str):
    return ROLE_BY_PREFIX.get((user_id or "")[:3].upper())


def load_seed_users(path=None):
    path = path or settings.SEED_USERS_FILE
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        log.warning("No seed users file at %s; nobody will be able to log in until one is created.", path)
        return []


def write_new_schema(db, new: dict, seed_users: list, actor=None, drop_existing=False):
    """Write transformed data, create logins for seed users, and record it in the ledger."""
    actor = actor or {"user_id": "SYSTEM", "role": "system"}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if drop_existing:
        for name in NEW_COLLECTIONS:
            db[name].drop()
    for name in ["courses", "batches", "students", "instructors", "admins", "marks", "attendance", "counters"]:
        if new.get(name):
            db[name].insert_many([dict(d) for d in new[name]])

    profiles = {
        "student": {s["student_code"] for s in new.get("students", [])},
        "instructor": {i["instructor_code"] for i in new.get("instructors", [])},
        "admin": {a["admin_code"] for a in new.get("admins", [])},
    }
    created = []
    for entry in seed_users:
        uid = entry["user_id"].strip().upper()
        role = role_for_user_id(uid)
        if role is None or uid not in profiles[role]:
            raise ValueError(f"Seed user {uid} has no matching student/instructor/admin record")
        db["users"].update_one(
            {"user_id": uid},
            {"$set": {"user_id": uid, "role": role, "password_hash": hash_password(entry["password"]),
                      "active": True, "must_change_password": False, "created_at": now}},
            upsert=True,
        )
        created.append(uid)

    ensure_indexes(db)
    ledger = Ledger(db)
    ledger.ensure_indexes()
    ledger.ensure_genesis()
    ledger.append(actor, "migrate_schema", None, {
        "counts": {k: len(v) for k, v in new.items() if isinstance(v, list) and k != "warnings"},
        "logins_created": created,
        "warnings": len(new.get("warnings", [])),
    })
    return created


def get_db():
    global _db
    if _db is not None:
        return _db
    if settings.MONGO_URI == "memory":
        from app.core.memdb import MemoryDB

        _db = MemoryDB()
        new = transform(load_legacy_json(settings.LEGACY_DATA_DIR), settings.DEFAULT_PASS_MARK)
        write_new_schema(_db, new, load_seed_users())
        log.warning("Running in MEMORY mode: data resets on restart. Set MONGO_URI to use MongoDB.")
    else:
        from pymongo import MongoClient

        client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=8000)
        _db = client[settings.MONGO_DB]
        if _db["users"].count_documents({}) == 0:
            log.warning("Database '%s' has no users. Run: python -m scripts.migrate", settings.MONGO_DB)
    return _db


def set_db(db):
    """Used by tests to inject a database."""
    global _db
    _db = db
