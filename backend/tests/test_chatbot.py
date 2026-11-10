"""Run from the backend folder:  python -m pytest -q
Uses the in-memory database and the bundled demo data; no network needed."""
import os

os.environ["MONGO_URI"] = "memory"
os.environ["LLM_API_KEY"] = ""

import pytest  # noqa: E402

from app.chatbot import engine as engine_mod  # noqa: E402
from app.chatbot.engine import ChatEngine  # noqa: E402
from app.config import settings  # noqa: E402
from app.core.db import load_seed_users, write_new_schema  # noqa: E402
from app.core.ledger import Ledger  # noqa: E402
from app.core.memdb import MemoryDB  # noqa: E402
from app.core.migration import load_legacy_json, transform  # noqa: E402
from app.core.security import verify_password  # noqa: E402

S = {"user_id": "STD001", "role": "student", "name": "Bonnie"}
I = {"user_id": "INS001", "role": "instructor", "name": "Dr. Meera Nair"}
A = {"user_id": "ADM001", "role": "admin", "name": "Arun Kumar"}


@pytest.fixture()
def db():
    d = MemoryDB()
    write_new_schema(d, transform(load_legacy_json(settings.LEGACY_DATA_DIR)), load_seed_users())
    return d


@pytest.fixture()
def bot(db, monkeypatch):
    monkeypatch.setattr(type(settings), "llm_enabled", property(lambda self: False))
    return ChatEngine(db)


def ask(bot, user, text, history=None):
    return bot.reply(user, text, history)


# ---------------------------------------------------------------- migration
def test_migration_and_logins(db):
    assert db["students"].count_documents({}) == 30
    assert db["courses"].find_one({"course_code": "C001"})["aliases"].count("Artificial Intelligence") == 1
    user = db["users"].find_one({"user_id": "STD001"})
    assert verify_password("amma@123", user["password_hash"])
    assert verify_password("teach@123", db["users"].find_one({"user_id": "INS001"})["password_hash"])
    assert verify_password("manage@123", db["users"].find_one({"user_id": "ADM001"})["password_hash"])
    assert db["users"].count_documents({}) == 3
    assert Ledger(db).verify()["valid"]


# ---------------------------------------------------------------- routing
@pytest.mark.parametrize("text,kind", [
    ("what are my marks", "lms"), ("did I pass?", "lms"), ("what's my attendance", "lms"),
    ("when is my next class", "lms"), ("who is my instructor", "lms"), ("what is the pass mark", "lms"),
    ("what is CNN", "general"), ("What is a neural network?", "general"), ("teach me recursion", "general"),
    ("explain backpropagation", "general"), ("hi", "greeting"), ("thanks!", "thanks"), ("who am i", "identity"),
])
def test_student_routing(bot, text, kind):
    assert ask(bot, S, text)["kind"] == kind


def test_student_answers_are_correct(bot):
    assert "84/100" in ask(bot, S, "what are my marks")["reply"]
    assert "92%" in ask(bot, S, "what's my attendance")["reply"]
    assert "Dr. Meera Nair" in ask(bot, S, "who is my instructor")["reply"]


def test_student_privacy(bot):
    for q in ["what are Rohan's marks", "how is Meera doing", "what is STD002's attendance"]:
        r = ask(bot, S, q)["reply"]
        assert "can't share" in r and "76" not in r and "88" not in r
    assert "can't share other students" in ask(bot, S, "what is the class average")["reply"]
    assert "can't change records" in ask(bot, S, "change my marks to 100")["reply"]


def test_followup_inherits_previous_topic(bot):
    hist = [{"role": "user", "content": "what are my marks"}, {"role": "assistant", "content": "You scored 84/100."}]
    r = ask(bot, S, "what about attendance?", hist)
    assert r["kind"] == "lms" and "92%" in r["reply"]
    hist = [{"role": "user", "content": "what is CNN"}, {"role": "assistant", "content": "A CNN is..."}]
    assert ask(bot, S, "explain it more simply", hist)["kind"] == "general"


def test_instructor_scope(bot):
    assert "Kavya" in ask(bot, I, "who is the top student in my class")["reply"]
    assert "isn't in your class" in ask(bot, I, "Rohan's marks")["reply"]
    assert "isn't in your class" in ask(bot, I, "how is Kiran doing")["reply"]
    assert "isn't one of your batches" in ask(bot, I, "show batch B1")["reply"]
    assert "made by the admin" in ask(bot, I, "add a student named Sam to A1")["reply"]


def test_admin_insights(bot):
    assert "30 students" in ask(bot, A, "how many students are there")["reply"]
    assert "D1" in ask(bot, A, "which batch has the lowest pass rate")["reply"]
    r = ask(bot, A, "failing students in batch D1")["reply"]
    assert "Kiran" in r and "Abhinav" in r
    assert "Which Meera" not in ask(bot, A, "how is Meera doing")["reply"]  # student data topic -> student Meera
    assert "intact" in ask(bot, A, "verify the audit ledger")["reply"]


# ---------------------------------------------------------------- admin actions
def test_add_student_needs_confirmation_and_logs(bot, db):
    r = ask(bot, A, "add a student named Riya Das to batch A1")
    assert r["pending_action"] and db["students"].count_documents({}) == 30
    r = ask(bot, A, "yes")
    assert "STD031" in r["reply"] and r["data"]["temporary_password"]
    assert db["students"].find_one({"student_code": "STD031"})["batch_code"] == "A1"
    assert db["users"].find_one({"user_id": "STD031"})
    led = Ledger(db)
    assert led.verify()["valid"] and led.list(1)[0]["action"] == "create_user"
    assert "temporary_password" not in str(led.list(1)[0]["details"])


def test_cancel_and_ambiguity(bot, db):
    ask(bot, A, "set marks of STD002 to 80")
    assert "cancelled" in ask(bot, A, "no")["reply"]
    assert db["marks"].find_one({"student_code": "STD002"})["marks"] == 76
    assert "Which one" in ask(bot, A, "reset password for Meera")["reply"]
    assert "own account" in ask(bot, A, "delete ADM001")["reply"]


def test_ledger_detects_tampering(db):
    led = Ledger(db)
    db["audit_ledger"].docs[1]["details"]["logins_created"] = ["HACKED"]
    v = led.verify()
    assert not v["valid"] and v["broken_at"] == 1


# ---------------------------------------------------------------- LLM guard
def test_llm_answer_with_invented_number_falls_back(db, monkeypatch):
    monkeypatch.setattr(type(settings), "llm_enabled", property(lambda self: True))
    monkeypatch.setattr(engine_mod.llm, "chat", lambda *a, **k: "You scored 97 out of 100, great job!")
    r = ChatEngine(db).reply(S, "what are my marks")
    assert r["source"] == "rules" and "84/100" in r["reply"]


def test_llm_answer_with_real_numbers_is_used(db, monkeypatch):
    monkeypatch.setattr(type(settings), "llm_enabled", property(lambda self: True))
    monkeypatch.setattr(engine_mod.llm, "chat", lambda *a, **k: "You scored 84 out of 100 in AI, a pass. Nice work, Bonnie!")
    r = ChatEngine(db).reply(S, "what are my marks")
    assert r["source"] == "llm" and "84" in r["reply"]


def test_general_question_gets_no_records(db, monkeypatch):
    seen = {}

    def fake_chat(messages, **kw):
        seen["system"] = messages[0]["content"]
        return "A CNN is a neural network for images."
    monkeypatch.setattr(type(settings), "llm_enabled", property(lambda self: True))
    monkeypatch.setattr(engine_mod.llm, "chat", fake_chat)
    monkeypatch.setattr(engine_mod.llm, "chat_json", lambda *a, **k: {"kind": "general"})
    r = ChatEngine(db).reply(S, "what is CNN")
    assert r["kind"] == "general" and "84" not in seen["system"] and "STUDENT RECORD" not in seen["system"]
