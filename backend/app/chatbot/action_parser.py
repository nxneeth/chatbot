"""Rule-based parser for common admin requests, so everyday changes work even
without a language model and never depend on the model getting JSON right.

Returns (action, question): an action dict when the request is complete,
a clarifying question when something is missing, or (None, None) when the
request doesn't match a known pattern (the LLM then takes over)."""
import re

ROLE_WORDS = {"student": "student", "students": "student", "instructor": "instructor", "teacher": "instructor",
              "faculty": "instructor", "admin": "admin", "administrator": "admin"}
LEAD = r"^(please |kindly |can you |could you |would you |i want to |i'd like to |i would like to |go ahead and |pls |plz )*"
STOP_NAME = r"(?:\s+(?:to|in|into|for|with|email|e-mail|phone|batch|password|pwd|as|who|and)\b|,|$)"


def _person(text, mentions, kind=None):
    """Return (code, question) for the single person referred to."""
    people = [p for p in mentions.people if kind is None or p.kind == kind]
    amb = {k: [p for p in v if kind is None or p.kind == kind] for k, v in mentions.ambiguous.items()}
    amb = {k: v for k, v in amb.items() if v}
    if len(people) == 1 and not amb:
        return people[0].code, None
    if not people and len(amb) == 1:
        cands = next(iter(amb.values()))
        if len(cands) == 1:
            return cands[0].code, None
        return None, "Which one do you mean: " + ", ".join(f"{c.name} ({c.code})" for c in cands) + "?"
    if len(people) > 1:
        return None, "That mentions more than one person (" + ", ".join(f"{p.name} {p.code}" for p in people) + "). Which one?"
    if mentions.unknown_codes:
        return None, f"I couldn't find anyone with ID {mentions.unknown_codes[0]}. Could you check it?"
    return None, None


def parse(text: str, mentions):
    raw = text.strip()
    t = re.sub(LEAD, "", raw, flags=re.I).strip().rstrip(".!")
    low = t.lower()
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", t)
    phone = re.search(r"\b(?:phone|mobile|number)\s*(?:is|:)?\s*(\+?\d[\d\s-]{6,}\d)", t, re.I)
    password = re.search(r"\b(?:password|pwd)\s*(?:is|=|:|as)?\s*(\S+)", t, re.I)
    batch = mentions.batches[0] if mentions.batches else None

    # ---- add / create a user -------------------------------------------
    m = re.match(r"(?:add|create|register|enrol|enroll|onboard)\s+(?:a\s+|an\s+)?(?:new\s+)?"
                 r"(student|instructor|teacher|faculty|admin|administrator)s?\b\s*(?:named|called|:|-)?\s*(.*)$", t, re.I)
    if m:
        role = ROLE_WORDS[m.group(1).lower()]
        rest = m.group(2)
        name_m = re.match(rf"([A-Za-z][A-Za-z .'-]*?){STOP_NAME}", rest)
        name = name_m.group(1).strip() if name_m else ""
        name = re.sub(r"^(mr|mrs|ms)\.?\s+", "", name, flags=re.I).strip()
        if name.lower().startswith(("dr ", "dr.", "prof ", "prof.")) and role != "instructor":
            pass
        if not name:
            return None, f"What's the new {role}'s full name?"
        payload = {"role": role, "name": name}
        if email:
            payload["email"] = email.group()
        if phone:
            payload["phone"] = re.sub(r"[\s-]", "", phone.group(1))
        if password:
            payload["password"] = password.group(1)
        if role == "student":
            if not batch:
                return None, f"Which batch should {name} join? (e.g. A1, B2, C3, D1)"
            payload["batch_code"] = batch
        elif role == "instructor" and mentions.batches:
            payload["batch_codes"] = mentions.batches
        return {"type": "create_user", "payload": payload}, None

    # ---- delete / remove a user --------------------------------------------
    m = re.match(r"(?:remove|delete|drop)\s+(?:the\s+)?(?:student|instructor|teacher|admin|user)?\s*(.*)$", t, re.I)
    if m and (mentions.people or mentions.ambiguous or mentions.unknown_codes) and not re.search(r"\b(course|batch|from)\b", low):
        code, q = _person(t, mentions)
        return ({"type": "delete_user", "payload": {"user_id": code}}, None) if code else (None, q)

    # ---- passwords / logins --------------------------------------------------
    if re.search(r"\b(reset|change|set)\b.*\bpassword\b|\b(give|create|make)\b.*\b(login|account)\b|\b(login|account) for\b", low):
        code, q = _person(t, mentions)
        if not code:
            return None, q or "Whose login is this for? Give a name or ID."
        payload = {"user_id": code}
        np = re.search(r"\b(?:to|as|password)\s+['\"]?([^\s'\"]{6,})['\"]?\s*$", t, re.I)
        if np and not re.match(r"(?i)(STD|INS|ADM)\d", np.group(1)):
            payload["new_password"] = np.group(1)
        return {"type": "reset_password", "payload": payload}, None

    # ---- enable / disable login ------------------------------------------------
    m = re.match(r"(disable|deactivate|block|suspend|enable|activate|unblock)\b", low)
    if m:
        code, q = _person(t, mentions)
        if not code:
            return None, q or "Whose login should I change?"
        active = m.group(1) in ("enable", "activate", "unblock")
        return {"type": "update_user", "payload": {"user_id": code, "fields": {"active": active}}}, None

    # ---- marks ----------------------------------------------------------------
    if re.search(r"\b(marks?|score)\b", low) and re.match(r"(set|update|change|record|enter|give|make)\b", low):
        code, q = _person(t, mentions, kind="student")
        if not code:
            return None, q or "Which student's marks should I set?"
        num = re.search(r"\b(?:to|=|as|is|:)\s*(\d+(?:\.\d+)?)\b", t) or re.search(r"\b(\d+(?:\.\d+)?)\s*(?:marks|/\s*100)\b", t)
        if not num:
            return None, "What marks should I record?"
        return {"type": "record_marks", "payload": {"student_code": code, "marks": float(num.group(1))}}, None

    # ---- attendance -------------------------------------------------------------
    if "attendance" in low and re.match(r"(set|update|change|record|enter|mark)\b", low):
        code, q = _person(t, mentions, kind="student")
        if not code:
            return None, q or "Which student's attendance should I update?"
        nums = re.search(r"(\d+)\s*(?:/|of|out of)\s*(\d+)", t)
        if not nums:
            return None, "How many classes attended, out of how many? (e.g. 42 of 50)"
        return {"type": "record_attendance", "payload": {"student_code": code, "classes_attended": int(nums.group(1)),
                                                          "total_classes": int(nums.group(2))}}, None

    # ---- move a student / assign an instructor -------------------------------------
    if re.match(r"(move|transfer|shift|enrol|enroll|put)\b", low) and batch:
        code, q = _person(t, mentions, kind="student")
        if not code:
            return None, q or "Which student should I move?"
        return {"type": "enroll_student", "payload": {"student_code": code, "batch_code": batch}}, None
    if re.match(r"(assign|make)\b", low) and batch:
        code, q = _person(t, mentions, kind="instructor")
        if not code:
            return None, q or "Which instructor should I assign?"
        return {"type": "assign_instructor", "payload": {"instructor_code": code, "batch_code": batch}}, None

    # ---- simple profile edits: "change Rohan's email to x@y.com" ---------------------
    m = re.match(r"(?:change|update|set|edit)\s+.*?\b(email|phone|name|progress|learning progress)\b.*?\bto\s+(.+)$", t, re.I)
    if m:
        code, q = _person(t, mentions)
        if not code:
            return None, q or "Whose details should I change?"
        field = {"email": "email", "phone": "phone", "name": "name", "progress": "learning_progress",
                 "learning progress": "learning_progress"}[m.group(1).lower()]
        value = m.group(2).strip().strip("'\"").rstrip("%")
        return {"type": "update_user", "payload": {"user_id": code, "fields": {field: value}}}, None

    return None, None
