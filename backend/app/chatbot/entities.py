"""Finds people, batches and courses mentioned in a message.

Names are matched carefully because many first names are shared between
students and staff (Arun, Meera, Priya, Kiran, Anjali, ...). A mention that
fits more than one person is returned as ambiguous and resolved later using
the user's scope and the topic of the question."""
import re
from dataclasses import dataclass, field

TITLE_RE = r"(?:dr|prof|professor|mr|mrs|ms|sir|madam|ma'am)\.?"
CODE_RE = re.compile(r"\b(STD|INS|ADM)\s*[-_]?\s*(\d{1,4})\b", re.I)


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


@dataclass
class Person:
    code: str
    name: str
    kind: str  # student / instructor / admin


@dataclass
class Mentions:
    people: list = field(default_factory=list)       # resolved Person objects
    ambiguous: dict = field(default_factory=dict)    # spoken name -> [Person, ...]
    batches: list = field(default_factory=list)
    courses: list = field(default_factory=list)
    unknown_codes: list = field(default_factory=list)

    @property
    def any_people(self):
        return bool(self.people or self.ambiguous)

    def codes(self, kind=None):
        return [p.code for p in self.people if kind is None or p.kind == kind]


class EntityIndex:
    def __init__(self, directory):
        d = directory
        self.people = {}
        for s in d.db["students"].find({}, {"_id": 0, "student_code": 1, "name": 1}):
            self.people[s["student_code"]] = Person(s["student_code"], s["name"], "student")
        for i in d.instructors():
            self.people[i["instructor_code"]] = Person(i["instructor_code"], i["name"], "instructor")
        for a in d.admins():
            self.people[a["admin_code"]] = Person(a["admin_code"], a["name"], "admin")
        self.batches = {b["batch_code"].upper() for b in d.batches()}
        self.courses = {}
        for c in d.courses():
            for alias in {c["name"], c["course_code"], *c.get("aliases", [])}:
                if alias:
                    self.courses[alias.lower()] = c["course_code"]

        # name tokens -> people ("meera" -> [STD005, INS001])
        self.by_token = {}
        self.full_names = []
        for p in self.people.values():
            clean = re.sub(TITLE_RE + r"\s+", "", p.name, flags=re.I).strip()
            parts = [x for x in re.findall(r"[a-z]+", clean.lower()) if len(x) > 1]
            if len(parts) > 1:
                self.full_names.append((" ".join(parts), p))
            for tok in parts:
                self.by_token.setdefault(tok, []).append(p)
        self.full_names.sort(key=lambda x: -len(x[0]))

    def find(self, text: str) -> Mentions:
        m = Mentions()
        work = " " + text + " "

        # 1. explicit IDs (STD001, ins 4, ADM-001)
        for prefix, num in CODE_RE.findall(work):
            code = f"{prefix.upper()}{int(num):03d}"
            if code in self.people:
                if self.people[code] not in m.people:
                    m.people.append(self.people[code])
            else:
                m.unknown_codes.append(code)
        work = CODE_RE.sub(" ", work)

        # 2. batches: uppercase A1/B2... or "batch a1"
        for tok in re.findall(r"\bbatch(?:es)?\s+([a-z]\d{1,2})\b", work, re.I):
            if tok.upper() in self.batches and tok.upper() not in m.batches:
                m.batches.append(tok.upper())
        for tok in re.findall(r"\b([A-Z]\d{1,2})\b", work):
            if tok in self.batches and tok not in m.batches:
                m.batches.append(tok)

        # 3. courses by name/alias
        low = work.lower()
        for alias, code in sorted(self.courses.items(), key=lambda kv: -len(kv[0])):
            if code in m.courses:
                continue
            if len(alias) <= 4:
                # short names like AI / DSA count when written in capitals or after "course"
                hit = re.search(rf"(?<![A-Za-z0-9]){re.escape(alias.upper())}(?![A-Za-z0-9])", work) or \
                    re.search(rf"\bcourse\s+{re.escape(alias)}\b", low)
            else:
                hit = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", low)
            if hit:
                m.courses.append(code)

        # 4. full names ("meera nair", "dr. nair" handled in step 5)
        low = re.sub(r"'s\b", "", low)
        low = re.sub(r"[^a-z\s]", " ", low)
        low = " " + re.sub(r"\s+", " ", low) + " "
        for full, p in self.full_names:
            if f" {full} " in low:
                if p not in m.people:
                    m.people.append(p)
                low = low.replace(f" {full} ", " ")

        # 5. single name tokens
        titled = set(re.findall(r"\b(?:dr|prof|professor)\s+([a-z]+)", low))
        for tok in re.findall(r"[a-z]+", low):
            cands = self.by_token.get(tok)
            if not cands:
                continue
            if tok in titled:
                cands = [c for c in cands if c.kind != "student"] or cands
            cands = [c for c in cands if c not in m.people]
            if not cands:
                continue
            if len(cands) == 1:
                m.people.append(cands[0])
            else:
                m.ambiguous[tok] = cands
        return m
