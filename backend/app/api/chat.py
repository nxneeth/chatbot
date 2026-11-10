from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import current_user, db_dep, require
from app.chatbot.engine import ChatEngine

router = APIRouter(prefix="/api/chat", tags=["chat"])


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=6000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = Field(default_factory=list, max_length=30)


@router.post("")
def chat(body: ChatIn, user=Depends(current_user), db=Depends(db_dep)):
    return ChatEngine(db).reply(user, body.message, [t.model_dump() for t in body.history])


@router.post("/actions/{action_id}/confirm")
def confirm(action_id: str, user=Depends(require("admin")), db=Depends(db_dep)):
    return ChatEngine(db).confirm(user, action_id)


@router.post("/actions/{action_id}/cancel")
def cancel(action_id: str, user=Depends(require("admin")), db=Depends(db_dep)):
    return ChatEngine(db).cancel(user, action_id)
