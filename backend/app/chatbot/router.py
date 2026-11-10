"""Decides WHERE an answer should come from before any model is called.

kinds:
  greeting / thanks / bye / help / identity  - conversation, no records needed
  lms        - the user's LMS records (marks, attendance, class, stats...)
  general    - general knowledge / tutoring ("what is CNN")
  action     - a request to change records (admin only; others are declined)
  confirm / cancel - answer to a pending admin action
  ambiguous  - rules are unsure; the LLM classifier (or a safe default) decides
"""
import re
from dataclasses import dataclass, field

TOPICS = {
    "marks": r"\b(marks?|scores?|scored|grades?|results?|pass(ed|ing)?|fail(ed|ing|ure)?|exams?|tests?|assessments?|mid-?terms?|finals?|rank(ing)?|position)\b",
    "attendance": r"\b(attendance|attend(ed|ing)?|present|absent|absences?|bunk(ed)?|missed classes|classes (i )?(missed|attended))\b",
    "progress": r"\b(progress|completion|completed|perform(ance|ing)?|standing|how (am i|is|are) [\w\s]*doing|how (am i|is|are) [\w\s]*going|am i doing|doing (well|good|ok|okay|fine|badly|poorly)|on track|behind|strengths?|weakness(es)?|weak areas)\b",
    "schedule": r"\b(schedule|timetable|time table|timings?|class times?|next class|when (is|are|do|does) [\w\s]*class(es)?)\b",
    "instructor": r"\b(instructors?|teachers?|faculty|professors?|lecturers?|mentors?|who teaches|taught by|teach(es|ing)?(?! (me|us)\b))\b",
    "course": r"\b(courses?|batch(es)?|enrolled|enrol(l)?ment|program(me)?s?|subjects?)\b",
    "students": r"\b(students?|class ?list|classmates|roster|who is in|who are in|learners|(the|my|our|whole|entire) class)\b",
    "contact": r"\b(e-?mail|phone|contact|mobile|number)\b",
    "policy": r"\b(pass(ing)? marks?|passing (score|criteria|grade)|minimum (marks|attendance)|attendance (requirement|criteria|rule)|required attendance|cut-?off)\b",
    "profile": r"\b(my (id|user ?id|email|phone|profile|details|account|name)|who am i)\b",
    "ledger": r"\b(audit|ledger|blockchain|checkpoints?|change ?log|tamper(ed|ing)?|history of changes)\b",
    "people": r"\b(admins?|administrators?|users?|accounts?|logins?|staff)\b",
}
STATS = r"\b(average|avg|mean|median|top(per|pers|s)?|highest|lowest|best|worst|ranks?|ranking|how many|count|total|number of|list|show( me)?|compare|comparison|summary|summari[sz]e|overview|stats|statistics|analytics|insights?|at[- ]risk|struggling|below|above|weak(est)?|strong(est)?|low|poor|high|pass rate|failing|failed|who (passed|failed)|everyone|all)\b"
FIRST_PERSON = r"\b(my|me|mine|i|i'm|im|i've|ive|myself|am i|did i|have i|do i|can i|should i|will i)\b"
OWN_CLASS = r"\b(my|our) (class(es)?|students|batch(es)?|section|learners|group)\b"
DEFINITIONAL = r"^(so |ok |okay |and |also |hey |hi |please |can you |could you )*(what (is|are|was|were|does|do)|what's|whats|explain|define|definition|describe|tell me about|how (does|do|is|are|can|to)|why (is|are|does|do)|difference between|give (me )?(an? )?example|teach me|meaning of|what do you mean by|types of|advantages|disadvantages)\b"
ADVICE = r"\b(improve|tips?|suggest(ion)?s?|advice|advise|how (can|should|do) i|help me|study plan|prepare|plan for|recommend)\b"
FOLLOWUP_WORDS = set("""it that this me an a another some more simply simpler simple please again can could you explain give example examples
i don't dont do not understand get what mean by in terms detail details elaborate clarify simplify tell go on continue short shorter eli5
and ok okay so how why the further bit little briefly brief say summarize summarise with words easier easy way differently better other still
clear confused am i'm im lost huh sorry one more detailed deeper detail""".split())
FOLLOWUP_CUES = r"(simpl|example|elaborate|detail|understand|clarify|what do you mean|in short|shorter|eli5|explain (it|that|this|again|more|better|differently)|tell me more|go on|continue|confus|lost|^why\b|^how\b)"
WHAT_ABOUT = r"^(what about|how about|and( what about)?|what of)\b"

GREETING = r"^(hi+|hello+|hey+|hiya|yo|good (morning|afternoon|evening|day)|namaste|greetings|howdy|sup|what'?s up)\b[\s!.,a-z]{0,25}$"
THANKS = r"^((ok(ay)?|great|cool|nice|perfect|awesome|got it)[\s,!.]*)?(thanks?( you)?( so much| a lot)?|thx|ty|thank u|much appreciated|great,? thanks)[\s!.]*$|^(ok(ay)?|got it|cool|nice|great|perfect|awesome|alright)[\s!.]*$"
BYE = r"^(bye|goodbye|see you|see ya|good night|gn|cya|that'?s all|take care)\b[\s!.]*"
HELP = r"^(help|menu|what can you do|what do you do|how can you help|what can i ask( you)?|what are you|who are you|options)[\s?!.]*$"
IDENTITY = r"^(who am i|what('?s| is) my (name|id|user ?id|role)|whoami)[\s?!.]*$"

ACTION_LEAD = r"^(please |kindly |can you |could you |would you |i want to |i'd like to |i would like to |go ahead and |pls |plz )*"
ACTION_VERBS = (r"(add|create|register|enrol|enroll|onboard|remove|delete|drop|deactivate|disable|enable|activate|"
                r"update|change|edit|modify|rename|set|reset|assign|move|transfer|record|mark|give|make|upload|import)\b")
ACTION_OBJECTS = r"\b(students?|instructors?|teachers?|admins?|users?|accounts?|logins?|passwords?|courses?|batch(es)?|marks?|scores?|attendance|progress|email|phone|name|STD\d+|INS\d+|ADM\d+)\b"

CONFIRM = r"^(yes|y|yeah|yep|yup|confirm(ed)?|ok(ay)?|go ahead|do it|proceed|sure|correct|approved?|looks good|that'?s right)[\s!.]*$"
CANCEL = r"^(no|n|nope|cancel|stop|abort|don'?t|do not|never ?mind|leave it|forget it|not now)[\s!.]*$"


@dataclass
class Route:
    kind: str
    topics: set = field(default_factory=set)
    stats: bool = False
    first_person: bool = False
    own_class: bool = False
    definitional: bool = False
    advice: bool = False
    followup: bool = False
    score: int = 0
    reason: str = ""


def _has(pattern, text):
    return re.search(pattern, text, re.I) is not None


def topics_in(text):
    return {name for name, pat in TOPICS.items() if _has(pat, text)}


def is_action_request(text):
    t = re.sub(ACTION_LEAD, "", text.strip().lower())
    return bool(re.match(ACTION_VERBS, t)) and _has(ACTION_OBJECTS, text) and not _has(r"^(set|show|list) of\b", t)


def route(text: str, mentions, role: str, has_pending=False) -> Route:
    raw = text.strip()
    t = re.sub(r"\s+", " ", raw.lower())

    if has_pending and _has(CONFIRM, t):
        return Route("confirm", reason="confirmation of pending action")
    if has_pending and _has(CANCEL, t):
        return Route("cancel", reason="cancel pending action")

    topics = topics_in(t)
    if _has(IDENTITY, t):
        return Route("identity", topics={"profile"})
    if _has(HELP, t):
        return Route("help")
    if _has(THANKS, t):
        return Route("thanks")
    if _has(BYE, t) and len(t.split()) <= 5:
        return Route("bye")
    if _has(GREETING, t) and not topics and not mentions.any_people:
        return Route("greeting")

    if is_action_request(raw):
        return Route("action", topics=topics, reason="action verb + record object")

    words = re.findall(r"[a-z']+", t)
    if words and _has(FOLLOWUP_CUES, t) and all(w in FOLLOWUP_WORDS for w in words):
        return Route("followup", followup=True, reason="follow-up phrase")
    if _has(WHAT_ABOUT, t) and len(words) <= 6:
        return Route("followup", topics=topics, followup=True, reason="what-about follow-up")

    r = Route("ambiguous", topics=topics)
    r.stats = _has(STATS, t)
    r.first_person = _has(FIRST_PERSON, t)
    r.own_class = _has(OWN_CLASS, t)
    r.definitional = _has(DEFINITIONAL, t)
    r.advice = _has(ADVICE, t)
    data_topics = topics - {"course"}
    people = mentions.any_people
    places = bool(mentions.batches)
    course_ref = bool(mentions.courses) and bool(topics & {"instructor", "schedule", "students", "marks", "attendance", "progress", "policy"})

    score = 0
    if topics & {"contact"} and people:
        score += 3
    if r.first_person and topics:
        score += 3
    if (people or places or course_ref) and (topics or r.stats):
        score += 3
    if r.own_class and role in ("instructor", "admin"):
        score += 3
    if r.stats and topics & {"students", "instructor", "marks", "attendance", "progress", "people", "course"}:
        score += 3
    if "policy" in topics:
        score += 3
    if "ledger" in topics and role == "admin":
        score += 3
    if people and not r.definitional and len(t.split()) <= 4:
        score += 3  # "Rohan?", "tell me Kiran"
    strong = score
    if data_topics and not r.definitional:
        score += 1
    if r.definitional and strong == 0:
        score -= 2
    r.score = score

    if score >= 3:
        r.kind, r.reason = "lms", f"score {score}"
    elif score <= 0:
        r.kind, r.reason = "general", f"score {score}"
    else:
        r.reason = f"score {score}"
    return r


def default_for_ambiguous(r: Route) -> str:
    """Used when the LLM classifier is unavailable."""
    if r.topics - {"course"} and not r.definitional:
        return "lms"
    return "general"
