"""routers/agent.py — GALOP AI Agent endpoint'leri"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import os, sys
sys.path.insert(0, '/app')

router = APIRouter()

# Conversation history (basit in-memory, production'da Redis kullan)
_sessions = {}

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"

class BriefingRequest(BaseModel):
    date_str: Optional[str] = None

@router.post("/chat")
async def agent_chat(req: ChatRequest):
    try:
        from agent import chat
        history = _sessions.get(req.session_id, [])
        response, new_history = chat(req.message, history)
        _sessions[req.session_id] = new_history[-20:]  # Son 20 mesaj
        return {"response": response, "session_id": req.session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/briefing")
async def daily_briefing(req: BriefingRequest = None):
    try:
        from agent import daily_briefing
        result = daily_briefing()
        return {"briefing": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    _sessions.pop(session_id, None)
    return {"status": "cleared"}
