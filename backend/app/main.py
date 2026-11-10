"""EduLayne API. Run from the backend folder:  uvicorn app.main:app --reload --port 8000"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, chat, portal
from app.config import settings
from app.core.db import get_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")



@asynccontextmanager
async def lifespan(_app):
    get_db()  # connect (or build the in-memory demo database) at startup
    yield


app = FastAPI(title="EduLayne API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(portal.router)
app.include_router(admin.router)
app.include_router(chat.router)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "database": "memory (demo)" if settings.MONGO_URI == "memory" else settings.MONGO_DB,
        "llm": settings.LLM_MODEL if settings.llm_enabled else "not configured (template answers only)",
    }
