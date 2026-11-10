"""Tamper-evident audit ledger (the blockchain provision).

Every change to LMS records is appended as a block:

    hash = SHA-256( index | timestamp | actor | action | target | details | prev_hash )

Each block stores the previous block's hash, so editing or deleting any past
entry breaks every hash after it, and `verify()` reports exactly where.

`create_checkpoint()` records the current head hash in `ledger_checkpoints`.
That is the anchoring hook: to anchor on a public chain later, publish the
same head hash in a transaction (see anchor_to_chain below) and store the
transaction id on the checkpoint.
"""
import hashlib
import json
from datetime import datetime, timezone

GENESIS_PREV = "0" * 64
SENSITIVE_KEYS = {"password", "password_hash", "temporary_password", "new_password"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _scrub(value):
    if isinstance(value, dict):
        return {k: ("***" if k in SENSITIVE_KEYS else _scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def compute_hash(block: dict) -> str:
    body = {k: block[k] for k in ("index", "timestamp", "actor", "action", "target", "details", "prev_hash")}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


class Ledger:
    def __init__(self, db):
        self.col = db["audit_ledger"]
        self.checkpoints = db["ledger_checkpoints"]

    def ensure_indexes(self):
        self.col.create_index("index", unique=True)

    def head(self):
        for block in self.col.find({}, {"_id": 0}).sort("index", -1).limit(1):
            return block
        return None

    def ensure_genesis(self):
        if self.head() is None:
            self.append({"user_id": "SYSTEM", "role": "system"}, "genesis", None, {"note": "EduLayne audit ledger created"})

    def append(self, actor: dict, action: str, target, details: dict) -> dict:
        for _ in range(5):  # retry if two writers race for the same index
            head = self.head()
            block = {
                "index": 0 if head is None else head["index"] + 1,
                "timestamp": _now(),
                "actor": {"user_id": actor.get("user_id"), "role": actor.get("role")},
                "action": action,
                "target": target,
                "details": _scrub(details or {}),
                "prev_hash": GENESIS_PREV if head is None else head["hash"],
            }
            block["hash"] = compute_hash(block)
            try:
                self.col.insert_one(dict(block))
                return block
            except Exception as exc:  # duplicate key from the unique index
                if "duplicate" not in str(exc).lower():
                    raise
        raise RuntimeError("Could not append to the audit ledger")

    def list(self, limit: int = 50, skip: int = 0):
        return list(self.col.find({}, {"_id": 0}).sort("index", -1).skip(skip).limit(limit))

    def verify(self) -> dict:
        prev_hash = GENESIS_PREV
        count = 0
        for block in self.col.find({}, {"_id": 0}).sort("index", 1):
            if block["index"] != count:
                return {"valid": False, "blocks": count, "broken_at": count, "reason": f"Block {count} is missing"}
            if block["prev_hash"] != prev_hash:
                return {"valid": False, "blocks": count, "broken_at": block["index"],
                        "reason": f"Block {block['index']} does not link to the block before it"}
            if compute_hash(block) != block["hash"]:
                return {"valid": False, "blocks": count, "broken_at": block["index"],
                        "reason": f"Block {block['index']} was modified after it was written"}
            prev_hash = block["hash"]
            count += 1
        return {"valid": True, "blocks": count, "head_hash": prev_hash if count else None}

    def create_checkpoint(self, actor: dict) -> dict:
        result = self.verify()
        if not result["valid"]:
            raise ValueError("Ledger failed verification; checkpoint not created. " + result["reason"])
        checkpoint = {
            "created_at": _now(),
            "created_by": actor.get("user_id"),
            "blocks": result["blocks"],
            "head_hash": result["head_hash"],
            "chain_tx": anchor_to_chain(result["head_hash"]),
        }
        self.checkpoints.insert_one(dict(checkpoint))
        return checkpoint

    def list_checkpoints(self, limit: int = 20):
        return list(self.checkpoints.find({}, {"_id": 0}).sort("created_at", -1).limit(limit))


def anchor_to_chain(head_hash: str):
    """Blockchain anchoring hook.

    Returns None today (checkpoints are stored only in MongoDB). To anchor on a
    public chain, send `head_hash` as the data of a transaction (for example with
    web3.py on Polygon Amoy or Ethereum Sepolia) and return the transaction hash.
    Anyone can then prove the ledger existed in this exact state at that time.
    """
    return None
