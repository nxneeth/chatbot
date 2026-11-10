"""A tiny in-memory stand-in for pymongo, used for offline demo mode and tests.

It supports only the subset of the pymongo API that EduLayne uses:
find / find_one / insert_one / insert_many / update_one / update_many /
delete_one / delete_many / count_documents / find_one_and_update /
create_index, with filters using equality, $in, $nin, $ne, $gt(e), $lt(e),
$exists, $or, $regex and updates using $set, $unset, $inc, $push, $pull.
"""
import copy
import itertools
import re

_ids = itertools.count(1)


def _match_value(value, cond):
    if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
        for op, arg in cond.items():
            if op == "$in" and value not in arg:
                return False
            if op == "$nin" and value in arg:
                return False
            if op == "$ne" and value == arg:
                return False
            if op == "$gt" and not (value is not None and value > arg):
                return False
            if op == "$gte" and not (value is not None and value >= arg):
                return False
            if op == "$lt" and not (value is not None and value < arg):
                return False
            if op == "$lte" and not (value is not None and value <= arg):
                return False
            if op == "$exists" and (value is not None) != bool(arg):
                return False
            if op == "$regex":
                flags = re.I if "i" in cond.get("$options", "") else 0
                if value is None or not re.search(arg, str(value), flags):
                    return False
        return True
    return value == cond


def _matches(doc, flt):
    if not flt:
        return True
    for key, cond in flt.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        if not _match_value(doc.get(key), cond):
            return False
    return True


def _apply_update(doc, update):
    for op, fields in update.items():
        for k, v in fields.items():
            if op == "$set":
                doc[k] = copy.deepcopy(v)
            elif op == "$unset":
                doc.pop(k, None)
            elif op == "$inc":
                doc[k] = doc.get(k, 0) + v
            elif op == "$push":
                doc.setdefault(k, []).append(copy.deepcopy(v))
            elif op == "$pull":
                doc[k] = [x for x in doc.get(k, []) if not (_matches(x, v) if isinstance(v, dict) else x == v)]
            elif op == "$setOnInsert":
                pass
            else:
                raise NotImplementedError(op)


class _Result:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        if isinstance(key, list):
            for k, d in reversed(key):
                self._docs.sort(key=lambda x: (x.get(k) is None, x.get(k)), reverse=d < 0)
        else:
            self._docs.sort(key=lambda x: (x.get(key) is None, x.get(key)), reverse=direction < 0)
        return self

    def limit(self, n):
        if n:
            self._docs = self._docs[:n]
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    def __iter__(self):
        return iter(self._docs)


class Collection:
    def __init__(self, name):
        self.name = name
        self.docs = []

    def _project(self, doc, projection):
        out = copy.deepcopy(doc)
        if projection and projection.get("_id") == 0:
            out.pop("_id", None)
        return out

    def find(self, flt=None, projection=None):
        return Cursor([self._project(d, projection) for d in self.docs if _matches(d, flt or {})])

    def find_one(self, flt=None, projection=None):
        for d in self.docs:
            if _matches(d, flt or {}):
                return self._project(d, projection)
        return None

    def insert_one(self, doc):
        doc.setdefault("_id", f"mem{next(_ids):08d}")
        self.docs.append(copy.deepcopy(doc))
        return _Result(inserted_id=doc["_id"])

    def insert_many(self, docs):
        ids = [self.insert_one(d).inserted_id for d in docs]
        return _Result(inserted_ids=ids)

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                _apply_update(d, update)
                return _Result(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            new = {k: v for k, v in flt.items() if not k.startswith("$") and not isinstance(v, dict)}
            new.update(update.get("$setOnInsert", {}))
            _apply_update(new, {k: v for k, v in update.items() if k != "$setOnInsert"})
            res = self.insert_one(new)
            return _Result(matched_count=0, modified_count=0, upserted_id=res.inserted_id)
        return _Result(matched_count=0, modified_count=0, upserted_id=None)

    def update_many(self, flt, update):
        n = 0
        for d in self.docs:
            if _matches(d, flt):
                _apply_update(d, update)
                n += 1
        return _Result(matched_count=n, modified_count=n)

    def find_one_and_update(self, flt, update, upsert=False, return_document=False, projection=None):
        for d in self.docs:
            if _matches(d, flt):
                before = copy.deepcopy(d)
                _apply_update(d, update)
                return self._project(d if return_document else before, projection)
        if upsert:
            self.update_one(flt, update, upsert=True)
            return self._project(self.docs[-1], projection) if return_document else None
        return None

    def delete_one(self, flt):
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                del self.docs[i]
                return _Result(deleted_count=1)
        return _Result(deleted_count=0)

    def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, flt or {})]
        return _Result(deleted_count=before - len(self.docs))

    def count_documents(self, flt=None):
        return sum(1 for d in self.docs if _matches(d, flt or {}))

    def create_index(self, *args, **kwargs):
        return "noop"

    def drop(self):
        self.docs = []


class MemoryDB:
    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = Collection(name)
        return self._cols[name]

    def list_collection_names(self):
        return [n for n, c in self._cols.items() if c.docs]
