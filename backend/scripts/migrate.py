"""One-time migration from the original LMS collections to the EduLayne v2 schema.

Your original database is only READ; everything is written to a new database
(MONGO_DB in .env, default "edulayne"), so you can always go back.

Usage (from the backend folder):
    python -m scripts.migrate --dry-run                 # show what would change
    python -m scripts.migrate                           # read old DB "LMS", write MONGO_DB
    python -m scripts.migrate --source-db LMS --reset   # rebuild the target from scratch
    python -m scripts.migrate --from-json data/legacy   # use Compass JSON exports instead
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.core.db import load_seed_users, write_new_schema  # noqa: E402
from app.core.migration import LEGACY_COLLECTIONS, NEW_COLLECTIONS, _strip_ext_json, load_legacy_json, transform  # noqa: E402


def read_source(args):
    if args.from_json:
        return load_legacy_json(Path(args.from_json))
    from pymongo import MongoClient

    client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=8000)
    src = client[args.source_db]
    return {name: [_strip_ext_json(d) for d in src[name].find({})] for name in LEGACY_COLLECTIONS}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-db", default="LMS", help="database holding the original collections (default: LMS)")
    parser.add_argument("--from-json", help="folder of Compass exports (LMS.students.json, ...) instead of a database")
    parser.add_argument("--reset", action="store_true", help="drop the target collections first")
    parser.add_argument("--dry-run", action="store_true", help="print the result without writing")
    args = parser.parse_args()

    old = read_source(args)
    print("Source:", ", ".join(f"{k}={len(v)}" for k, v in old.items()))
    new = transform(old, settings.DEFAULT_PASS_MARK)
    print("Target:", ", ".join(f"{k}={len(v)}" for k, v in new.items() if k != "warnings"))
    if new["warnings"]:
        print(f"\n{len(new['warnings'])} data notes:")
        for w in new["warnings"]:
            print("  -", w)
    seed = load_seed_users()
    print("\nLogins to create:", ", ".join(u["user_id"] for u in seed) or "(none)")

    if args.dry_run:
        print("\nDry run: nothing written.")
        return
    if settings.MONGO_URI == "memory":
        sys.exit("MONGO_URI is 'memory'. Set your MongoDB connection string in backend/.env first.")

    from pymongo import MongoClient

    db = MongoClient(settings.MONGO_URI)[settings.MONGO_DB]
    if args.source_db == settings.MONGO_DB and not args.from_json:
        sys.exit("Source and target databases are the same. Set MONGO_DB to a new name (e.g. edulayne).")
    existing = [c for c in NEW_COLLECTIONS if db[c].count_documents({}) > 0]
    if existing and not args.reset:
        sys.exit(f"Target database '{settings.MONGO_DB}' already has data in {existing}. Use --reset to rebuild it.")
    if args.reset:
        db["audit_ledger"].drop()
        db["ledger_checkpoints"].drop()
        db["pending_actions"].drop()
    created = write_new_schema(db, new, seed, drop_existing=args.reset)
    print(f"\nDone. Wrote database '{settings.MONGO_DB}'. Logins created: {', '.join(created)}")


if __name__ == "__main__":
    main()
