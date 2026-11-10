"""The chatbot pipeline:

    message -> find entities -> route -> scope check -> facts -> answer -> number check

1. The ROUTER decides where the answer comes from (records, general knowledge,
   conversation, or an admin action) using rules, with an LLM classifier only
   for the few messages the rules can't settle.
2. SCOPE checks run in code, not in the prompt: a student never gets another
   student's data into the model's context, an instructor only their own
   batches, so the model cannot leak what it never sees.
3. FACTS are computed in Python (averages, pass rates, attendance %).
4. The LLM only words the answer. If it is unavailable, or its answer
   contains a number that is not in the facts, a template answer is used.
5. Admin changes become a pending action that runs only after Confirm.
"""
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from app.chatbot import facts as F
from app.chatbot import llm, prompts
from app.chatbot.action_parser import parse as parse_action
from app.chatbot.entities import EntityIndex, Mentions
from app.chatbot.router import default_for_ambiguous, route
from app.config import settings
from app.services.actions import ActionError, Actions
from app.services.directory import Directory

log = logging.getLogger("edulayne.chat")
STUDENT_DATA_TOPICS = {"marks", "attendance", "progress", "contact", "students"}
STAFF_TOPICS = {"instructor", "contact", "schedule"}
PENDING_TTL = timedelta(minutes=15)


def _now():
    return datetime.now(timezone.utc)


def _numbers(text):
    out = set()
    for n in re.findall(r"\d+(?:\.\d+)?", text or ""):
        f = float(n)
        out.add(round(f, 2))
    return out


class ChatEngine:
    def __init__(self, db):
        self.db = db
        self.dir = Directory(db)

    # ================================================================ public
    def reply(self, user: dict, message: str, history=None) -> dict:
        message = (message or "").strip()[:2000]
        history = [h for h in (history or []) if h.get("role") in ("user", "assistant") and h.get("content")][-10:]
        if not message:
            return self._out("Could you type your question?", "empty")
        index = EntityIndex(self.dir)
        mentions = index.find(message)
        pending = self._pending(user) if user["role"] == "admin" else None
        r = route(message, mentions, user["role"], has_pending=pending is not None)
        log.info("route %s %s -> %s (%s)", user["user_id"], message[:60], r.kind, r.reason)

        if r.kind == "confirm":
            return self.confirm(user, pending["action_id"])
        if r.kind == "cancel":
            return self.cancel(user, pending["action_id"])
        if r.kind in ("greeting", "thanks", "bye", "help", "identity"):
            return self._out(self._conversation(user, r.kind), r.kind)
        if r.kind == "action":
            if user["role"] != "admin":
                return self._out(self._decline_change(user), "action")
            return self._admin_action(user, message, mentions, history)

        if r.kind == "followup":
            prev = self._previous_route(user, history, index)
            if prev is None:
                kind = default_for_ambiguous(r) if r.topics else "general"
            else:
                kind, prev_route, prev_mentions = prev
                if kind == "lms":
                    if not r.topics:
                        r.topics = prev_route.topics
                    r.first_person = prev_route.first_person
                    r.stats = prev_route.stats
                    mentions = self._merge(mentions, prev_mentions)
            r.kind = kind
        elif r.kind == "ambiguous":
            r.kind = self._classify(user, message, r)

        if r.kind == "lms":
            return self._lms(user, message, r, mentions, history)
        return self._general(user, message, history)

    def confirm(self, user, action_id):
        pending = self._pending(user, action_id)
        if not pending:
            return self._out("That request has expired or was already handled. Please ask again if you still need the change.", "confirm")
        self.db["pending_actions"].delete_one({"action_id": pending["action_id"]})
        try:
            result = Actions(self.db).execute(pending["action"], {"user_id": user["user_id"], "role": user["role"]})
        except ActionError as e:
            return self._out(f"That change couldn't be made: {e}", "confirm")
        text = "Done. " + result["message"]
        temp = (result.get("data") or {}).get("temporary_password")
        if temp:
            text += f"\n\nTemporary password: **{temp}**\n\nShare it with them privately; it won't be shown again, and they'll be asked to change it."
        return self._out(text, "confirm", data=result.get("data"))

    def cancel(self, user, action_id):
        self.db["pending_actions"].delete_many({"user_id": user["user_id"]})
        return self._out("Okay, cancelled. Nothing was changed.", "cancel")

    # ========================================================== conversation
    def _conversation(self, user, kind):
        name, role = user["name"], user["role"]
        if kind == "greeting":
            return f"Hi {name}! How can I help you today?"
        if kind == "thanks":
            return "You're welcome! Anything else I can help with?"
        if kind == "bye":
            return f"Goodbye, {name}! " + ("Good luck with your studies." if role == "student" else "Have a good day.")
        if kind == "identity":
            if role == "student":
                row = self.dir.student_row(user["user_id"])
                if row:
                    return f"You're **{row['name']}** ({row['student_code']}), a student in {row['course_name']}, batch {row['batch_code']}."
            label = {"student": "a student", "instructor": "an instructor", "admin": "an administrator"}[role]
            return f"You're **{name}** ({user['user_id']}), {label} on EduLayne."
        return {
            "student": "I can help you with:\n- **Your records**: marks, result, attendance, learning progress, schedule, instructor\n"
                       "- **Studying**: explanations of any topic, examples, revision help and study plans\n\n"
                       "Try *\"What's my attendance?\"* or *\"Explain CNNs simply\"*.",
            "instructor": "I can help you with:\n- **Your class**: marks, attendance, progress and who may need support\n"
                          "- **Teaching**: lesson plans, quiz questions, rubrics and explanations\n\n"
                          "Try *\"Who has low attendance in my class?\"* or *\"Make 5 quiz questions on backpropagation\"*.",
            "admin": "I can help you with:\n- **Insights**: totals, course and batch performance, failing or low-attendance students\n"
                     "- **Changes**: add, update or remove students, instructors and admins; marks; attendance; courses; batches\n"
                     "- **Audit ledger**: verify the change history\n\n"
                     "Try *\"Which batch has the lowest pass rate?\"* or *\"Add a student named Riya Das to batch A1\"*. "
                     "Every change asks for your confirmation first.",
        }[role]

    def _decline_change(self, user):
        if user["role"] == "student":
            return ("I can't change records from here. If something looks wrong with your marks, attendance or details, "
                    "please contact your instructor or the admin.")
        return "Changes to records are made by the admin. Let them know what needs updating and they can do it in a few seconds."

    # ================================================================ routing
    def _classify(self, user, message, r):
        if settings.llm_enabled:
            try:
                out = llm.chat_json([
                    {"role": "system", "content": prompts.ROUTER_PROMPT.replace("{role}", user["role"])},
                    {"role": "user", "content": message},
                ])
                if out.get("kind") in ("lms", "general"):
                    return out["kind"]
            except llm.LLMError as e:
                log.info("classifier unavailable: %s", e)
        return default_for_ambiguous(r)

    def _previous_route(self, user, history, index, depth=0):
        users = [h["content"] for h in history if h["role"] == "user"]
        for text in reversed(users[-3:]):
            m = index.find(text)
            r = route(text, m, user["role"])
            if r.kind == "followup":
                continue
            if r.kind == "ambiguous":
                r.kind = default_for_ambiguous(r)
            if r.kind in ("lms", "general"):
                return r.kind, r, m
            return None
        return None

    @staticmethod
    def _merge(a: Mentions, b: Mentions) -> Mentions:
        if a.any_people or a.batches or a.courses:
            return a
        return b

    # ==================================================================== LMS
    def _lms(self, user, message, r, mentions, history):
        role = user["role"]
        facts = F.Facts(self.db, user)
        low = message.lower()

        if role == "student":
            row = facts.dir.student_row(user["user_id"])
            others = self._resolve(mentions, r, allowed_students={user["user_id"]}, role=role, own_instructor=row and row["instructor_code"])
            if others.get("refuse"):
                return self._out("I can't share another student's records. I'm happy to help with your own progress, "
                                 "or with any topic you're studying.", "lms")
            if r.stats and re.search(r"\b(class|batch|classmates|others|everyone|other students|rank|ranking|topper|position)\b", low):
                return self._out("I can't share other students' results or class rankings. Here's how you're doing:\n\n"
                                 + F.student_template(row, {"marks", "attendance", "progress"}), "lms")
            ctx = facts.student_context()
            template = F.student_template(ctx["row"], r.topics)
            staff = others.get("staff", [])
            if "instructor" in r.topics and (staff or mentions.batches or mentions.courses):
                template = self._faculty_lines(facts.dir, staff, mentions) or template
            return self._answer(user, message, history, ctx["text"], template)

        if role == "instructor":
            my_rows = facts.dir.instructor_student_rows(user["user_id"])
            mine = {x["student_code"] for x in my_rows}
            my_batches = {b["batch_code"] for b in facts.dir.instructor_batches(user["user_id"])}
            res = self._resolve(mentions, r, allowed_students=mine, role=role)
            if res.get("clarify"):
                return self._out(res["clarify"], "lms")
            if res.get("refuse"):
                return self._out(f"{res['refuse']} isn't in your class, so I can't share their records.", "lms")
            other_batches = [b for b in mentions.batches if b not in my_batches]
            if other_batches:
                return self._out(f"Batch {', '.join(other_batches)} isn't one of your batches, so I can't share its records.", "lms")
            focus = res.get("students", [])
            ctx = facts.instructor_context(focus_codes=focus)
            if focus:
                template = "\n\n".join(F.person_template(x) for x in my_rows if x["student_code"] in focus)
            else:
                rows = [x for x in my_rows if not mentions.batches or x["batch_code"] in mentions.batches]
                title = f"batch {', '.join(sorted({x['batch_code'] for x in rows}))}" if rows else "your class"
                template = F.group_template(title, rows, r.topics, message) if rows else "You don't have any students assigned yet."
            return self._answer(user, message, history, ctx["text"], template)

        # admin
        res = self._resolve(mentions, r, allowed_students=None, role=role)
        if res.get("clarify"):
            return self._out(res["clarify"], "lms")
        focus = res.get("students", [])
        ctx = facts.admin_context(route_topics=r.topics, focus={"students": focus})
        template = self._admin_template(facts, ctx["rows"], r, mentions, res, message)
        return self._answer(user, message, history, ctx["text"], template)

    def _resolve(self, mentions, r, allowed_students, role, own_instructor=None):
        """Turn mentions into in-scope student codes, or a refusal / clarifying question."""
        students = [p.code for p in mentions.people if p.kind == "student"]
        staff = [p.code for p in mentions.people if p.kind != "student"]
        for spoken, cands in mentions.ambiguous.items():
            stud = [c for c in cands if c.kind == "student"]
            stf = [c for c in cands if c.kind != "student"]
            if role == "student":
                if any(c.code in (allowed_students or ()) for c in stud):
                    continue  # their own name
                if stf and (r.topics & STAFF_TOPICS or not r.topics & STUDENT_DATA_TOPICS):
                    continue  # public faculty question
                if stud:
                    students.append(stud[0].code)
                continue
            if allowed_students is not None:
                stud = [c for c in stud if c.code in allowed_students] or stud
            if stud and (not stf or r.topics & STUDENT_DATA_TOPICS - {"contact"}):
                pick = stud
            elif stf and (r.topics & STAFF_TOPICS or not stud):
                pick = stf
            else:
                pick = stud + stf
            if len(pick) == 1:
                (students if pick[0].kind == "student" else staff).append(pick[0].code)
            else:
                return {"clarify": f"Which {spoken.title()} do you mean: " + ", ".join(f"{c.name} ({c.code})" for c in pick) + "?"}
        if allowed_students is not None:
            outside = [s for s in students if s not in allowed_students]
            if outside:
                name = next(p.name for p in EntityIndex(self.dir).people.values() if p.code == outside[0])
                return {"refuse": name}
        return {"students": students, "staff": staff}

    @staticmethod
    def _faculty_lines(d, staff, mentions):
        """Public faculty directory answer: who teaches which batch."""
        lines = []
        for b in d.batches():
            if b.get("instructor_code") in staff or b["batch_code"] in mentions.batches or b["course_code"] in mentions.courses:
                ins = d.instructor(b["instructor_code"]) if b.get("instructor_code") else None
                course = d.course(b["course_code"]) or {}
                lines.append(f"- Batch {b['batch_code']} ({course.get('name')}): {ins['name'] if ins else 'no instructor assigned'}")
        return "\n".join(lines)

    def _admin_template(self, facts, rows, r, mentions, res, message):
        low = message.lower()
        parts = []
        for code in res.get("students", []):
            row = next((x for x in rows if x["student_code"] == code), None)
            if row:
                parts.append(F.person_template(row, private=True) + f"\n- Login: {'yes' if row['has_login'] else 'no'}")
        for code in res.get("staff", []):
            ins = facts.dir.instructor(code)
            if ins:
                teaches = [b["batch_code"] for b in facts.dir.instructor_batches(code)]
                parts.append(f"**{ins['name']}** ({code}) · {ins.get('email') or 'no email'} · teaches {', '.join(teaches) or 'no batches'}")
            adm = facts.dir.admin(code)
            if adm:
                parts.append(f"**{adm['name']}** ({code}) · admin · {adm.get('email') or 'no email'} · {adm.get('phone') or 'no phone'}")
        if parts:
            return "\n\n".join(parts)
        if "ledger" in r.topics:
            from app.core.ledger import Ledger
            v = Ledger(self.db).verify()
            return (f"The audit ledger has **{v['blocks']} blocks** and the chain is "
                    + ("**intact**: no entry has been altered." if v["valid"] else f"**broken**: {v['reason']}."))
        if "instructor" in r.topics and (mentions.batches or mentions.courses) and not r.stats:
            lines = []
            for b in facts.dir.batches():
                if b["batch_code"] in mentions.batches or b["course_code"] in mentions.courses:
                    ins = facts.dir.instructor(b.get("instructor_code")) if b.get("instructor_code") else None
                    lines.append(f"- Batch {b['batch_code']}: {ins['name'] if ins else 'no instructor assigned'}")
            return "\n".join(lines)
        if "instructor" in r.topics and re.search(r"\b(list|all|show|who are)\b", low):
            return "\n".join(f"- {i['instructor_code']} {i['name']}: batches "
                             + ", ".join(b["batch_code"] for b in facts.dir.instructor_batches(i["instructor_code"]))
                             for i in facts.dir.instructors())
        if re.search(r"\bwhich (batch|course)\b", low):
            key = "batch_code" if "batch" in low else "course_code"
            from app.services.directory import group_stats
            stats = group_stats(rows, key)
            metric = "pass_rate" if "pass" in low else "average_attendance" if "attend" in low else "average_marks"
            ordered = sorted(stats.items(), key=lambda kv: (kv[1][metric] is None, kv[1][metric] or 0))
            best = ordered[-1] if re.search(r"\b(highest|best|top|most)\b", low) else ordered[0]
            label = metric.replace("_", " ")
            value = F.fmt(best[1][metric]) + ("" if metric == "average_marks" else "%")
            name = best[0] if key == "batch_code" else facts.dir.course(best[0])["name"]
            return f"{'Batch' if key == 'batch_code' else 'Course'} **{name}** has the {'highest' if best is ordered[-1] else 'lowest'} {label}: **{value}**."
        scope_rows = rows
        title = "the whole institution"
        if mentions.batches:
            scope_rows = [x for x in rows if x["batch_code"] in mentions.batches]
            title = "batch " + ", ".join(mentions.batches)
        elif mentions.courses:
            scope_rows = [x for x in rows if x["course_code"] in mentions.courses]
            title = ", ".join(facts.dir.course(c)["name"] for c in mentions.courses)
        if re.search(r"\bhow many\b", low) and not mentions.batches and not mentions.courses:
            b = facts.dir.batches()
            return (f"EduLayne has **{len(rows)} students**, **{len(facts.dir.instructors())} instructors**, "
                    f"**{len(facts.dir.admins())} admins**, **{len(facts.dir.courses())} courses** and **{len(b)} batches** "
                    f"({sum(1 for x in b if x.get('status') == 'Active')} active).")
        return F.group_template(title, scope_rows, r.topics, message)

    # ================================================================ answer
    def _answer(self, user, message, history, context, template):
        if not settings.llm_enabled:
            return self._out(template, "lms", source="rules")
        system = prompts.base_system(user) + prompts.LMS_MODE + "\n\n[AUTHORIZED DATA]\n" + context
        msgs = [{"role": "system", "content": system}] + history[-6:] + [{"role": "user", "content": message}]
        try:
            text = llm.chat(msgs, temperature=0.2)
        except llm.LLMError as e:
            log.warning("LLM failed, using template: %s", e)
            return self._out(template, "lms", source="rules")
        allowed = _numbers(context) | _numbers(message) | _numbers(template)
        for h in history:
            allowed |= _numbers(h["content"])
        today = date.today()
        allowed |= {float(today.day), float(today.year), float(today.month), float(settings.LOW_ATTENDANCE)}
        bad = [n for n in _numbers(text) if n not in allowed and n > 12]
        if bad:
            log.warning("Model answer had numbers not in the data %s; using template", bad)
            return self._out(template, "lms", source="rules")
        return self._out(text, "lms", source="llm")

    def _general(self, user, message, history):
        if not settings.llm_enabled:
            return self._out("I can answer study questions once the AI model is connected (set LLM_API_KEY in the backend .env). "
                             "Meanwhile I can tell you about your records: try asking about your marks, attendance or schedule.",
                             "general", source="rules")
        system = prompts.base_system(user) + prompts.GENERAL_MODE
        msgs = [{"role": "system", "content": system}] + history[-8:] + [{"role": "user", "content": message}]
        try:
            return self._out(llm.chat(msgs, temperature=0.5, max_tokens=1400), "general", source="llm")
        except llm.LLMError as e:
            log.warning("LLM failed for general question: %s", e)
            return self._out("I'm having trouble reaching the AI model right now. Please try again in a moment.", "general", source="rules")

    # ========================================================= admin actions
    def _admin_action(self, user, message, mentions, history):
        action, question = parse_action(message, mentions)
        source = "rules"
        if action is None and question is None:
            if not settings.llm_enabled:
                return self._out("I couldn't work out that change. Try a phrasing like *\"Add a student named Riya Das to batch A1\"*, "
                                 "*\"Set marks of STD002 to 80\"* or *\"Reset the password for STD019\"*, or use LMS Overview.", "action")
            system = (prompts.base_system(user) + prompts.ACTION_MODE + "\n[REFERENCE DATA]\n" + prompts.action_reference(self.dir))
            msgs = [{"role": "system", "content": system}] + history[-6:] + [{"role": "user", "content": message}]
            try:
                text = llm.chat(msgs, temperature=0, max_tokens=900)
            except llm.LLMError:
                return self._out("I'm having trouble reaching the AI model. Try a direct phrasing like "
                                 "*\"Add a student named Riya Das to batch A1\"*, or use LMS Overview.", "action")
            m = re.search(r"<ACTION>\s*(\{.*?\})\s*</ACTION>", text, re.S) or re.search(r"```(?:json)?\s*(\{.*?\"type\".*?\})\s*```", text, re.S)
            if not m:
                return self._out(text.strip(), "action", source="llm")
            try:
                action = json.loads(m.group(1))
            except json.JSONDecodeError:
                return self._out("I couldn't prepare that change. Could you rephrase it?", "action")
            source = "llm"
        if question:
            return self._out(question, "action")
        actor = {"user_id": user["user_id"], "role": user["role"]}
        try:
            checked = Actions(self.db).validate(action, actor)
        except ActionError as e:
            return self._out(f"I couldn't prepare that change: {e}", "action")
        pending = {
            "action_id": uuid.uuid4().hex[:12],
            "user_id": user["user_id"],
            "action": checked["action"],
            "summary": checked["summary"],
            "destructive": checked["destructive"],
            "created_at": _now().isoformat(),
            "expires_at": (_now() + PENDING_TTL).isoformat(),
        }
        self.db["pending_actions"].delete_many({"user_id": user["user_id"]})
        self.db["pending_actions"].insert_one(dict(pending))
        text = ("Please confirm this change:" if not checked["destructive"] else "Please confirm. **This cannot be undone:**")
        text += "\n" + "\n".join(f"- {line}" for line in checked["summary"])
        return self._out(text, "action", source=source, pending_action={
            "id": pending["action_id"], "summary": checked["summary"], "destructive": checked["destructive"], "type": checked["action"]["type"]})

    def _pending(self, user, action_id=None):
        flt = {"user_id": user["user_id"]}
        if action_id:
            flt["action_id"] = action_id
        doc = self.db["pending_actions"].find_one(flt, {"_id": 0})
        if doc and doc["expires_at"] < _now().isoformat():
            self.db["pending_actions"].delete_one({"action_id": doc["action_id"]})
            return None
        return doc

    @staticmethod
    def _out(reply, kind, source="rules", pending_action=None, data=None):
        out = {"reply": reply, "kind": kind, "source": source, "pending_action": pending_action}
        if data:
            out["data"] = data
        return out
