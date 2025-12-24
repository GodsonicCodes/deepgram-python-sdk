"""
Voltar AI Voice Sales Agent - FastAPI Backend
Main application with WebSocket and REST endpoints
"""

import os
import asyncio
import json
import uuid
from typing import Dict, Optional
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from voice_pipeline import VoicePipeline
from session_manager import SessionManager, Session
from lead_extractor import LeadExtractor

# Environment variables
PORT = int(os.getenv("PORT", 10000))
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-2")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Initialize FastAPI app
app = FastAPI(title="Voltar AI Voice Agent", version="1.0.0")

# CORS middleware for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global managers
session_manager = SessionManager()
lead_extractor = LeadExtractor()

# ==================== Pydantic Models ====================

class SessionStartRequest(BaseModel):
    userId: Optional[str] = None

class SessionStartResponse(BaseModel):
    sessionId: str
    websocketUrl: str

class SessionInfo(BaseModel):
    sessionId: str
    status: str
    duration: int
    messageCount: int

class SessionSummary(BaseModel):
    duration: int
    messageCount: int
    leadCaptured: bool

class SessionEndResponse(BaseModel):
    summary: SessionSummary

class TranscriptMessage(BaseModel):
    role: str
    text: str
    timestamp: int

class TranscriptResponse(BaseModel):
    messages: list[TranscriptMessage]

class LeadRequest(BaseModel):
    sessionId: str
    name: str
    email: str
    phone: str
    painPoints: list[str]
    interestLevel: str

class LeadResponse(BaseModel):
    leadId: str
    qualificationScore: int

class HealthResponse(BaseModel):
    status: str
    services: Dict[str, str]

# ==================== REST API Endpoints ====================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Voltar AI Voice Agent",
        "version": "1.0.0",
        "status": "running"
    }

@app.post("/api/sessions/start", response_model=SessionStartResponse)
async def start_session(request: SessionStartRequest):
    """Start a new voice session"""
    session_id = str(uuid.uuid4())
    session = session_manager.create_session(session_id, request.userId)

    # WebSocket URL (adjust for your deployment)
    ws_url = f"ws://localhost:{PORT}/ws/voice-session"

    return SessionStartResponse(
        sessionId=session_id,
        websocketUrl=ws_url
    )

@app.get("/api/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    """Get session information"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionInfo(
        sessionId=session.session_id,
        status=session.status,
        duration=session.get_duration(),
        messageCount=len(session.messages)
    )

@app.post("/api/sessions/{session_id}/end", response_model=SessionEndResponse)
async def end_session(session_id: str):
    """End a session and get summary"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session_manager.end_session(session_id)

    return SessionEndResponse(
        summary=SessionSummary(
            duration=session.get_duration(),
            messageCount=len(session.messages),
            leadCaptured=session.lead_captured
        )
    )

@app.get("/api/sessions/{session_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(session_id: str):
    """Get session transcript"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = [
        TranscriptMessage(
            role=msg["role"],
            text=msg["text"],
            timestamp=msg["timestamp"]
        )
        for msg in session.messages
    ]

    return TranscriptResponse(messages=messages)

@app.post("/api/leads", response_model=LeadResponse)
async def create_lead(request: LeadRequest):
    """Create a lead from session data"""
    lead_id = str(uuid.uuid4())

    # Calculate qualification score
    score = lead_extractor.calculate_qualification_score(
        interest_level=request.interestLevel,
        pain_points=request.painPoints,
        has_contact=bool(request.email or request.phone)
    )

    # Save lead data
    lead_data = {
        "lead_id": lead_id,
        "session_id": request.sessionId,
        "name": request.name,
        "email": request.email,
        "phone": request.phone,
        "pain_points": request.painPoints,
        "interest_level": request.interestLevel,
        "qualification_score": score,
        "created_at": datetime.utcnow().isoformat()
    }

    lead_extractor.save_lead(lead_data)

    # Mark session as having captured lead
    session = session_manager.get_session(request.sessionId)
    if session:
        session.lead_captured = True

    return LeadResponse(leadId=lead_id, qualificationScore=score)

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    services = {
        "deepgram": "up" if DEEPGRAM_API_KEY else "down",
        "claude": "up" if ANTHROPIC_API_KEY else "down"
    }

    status = "healthy" if all(s == "up" for s in services.values()) else "degraded"

    return HealthResponse(status=status, services=services)

# ==================== WebSocket Endpoint ====================

@app.websocket("/ws/voice-session")
async def voice_session_websocket(websocket: WebSocket):
    """Main WebSocket endpoint for voice sessions"""
    await websocket.accept()

    session_id: Optional[str] = None
    pipeline: Optional[VoicePipeline] = None

    try:
        async for message in websocket.iter_text():
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "start_session":
                # Initialize session
                user_id = data.get("userId")
                session_id = str(uuid.uuid4())

                session = session_manager.create_session(session_id, user_id)

                # Create voice pipeline
                pipeline = VoicePipeline(
                    session_id=session_id,
                    websocket=websocket,
                    session_manager=session_manager,
                    lead_extractor=lead_extractor,
                    deepgram_api_key=DEEPGRAM_API_KEY,
                    anthropic_api_key=ANTHROPIC_API_KEY,
                    deepgram_model=DEEPGRAM_MODEL,
                    claude_model=CLAUDE_MODEL
                )

                # Start pipeline
                asyncio.create_task(pipeline.start())

                # Send session started response
                await websocket.send_json({
                    "type": "session_started",
                    "sessionId": session_id,
                    "websocketUrl": f"ws://localhost:{PORT}/ws/voice-session"
                })

            elif msg_type == "end_session":
                if pipeline:
                    await pipeline.stop()
                if session_id:
                    session_manager.end_session(session_id)
                break

            elif msg_type == "interrupt":
                if pipeline:
                    await pipeline.handle_interrupt()

    except WebSocketDisconnect:
        print(f"WebSocket disconnected for session {session_id}")
    except Exception as e:
        print(f"Error in WebSocket: {e}")
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })
    finally:
        if pipeline:
            await pipeline.cleanup()
        if session_id:
            session_manager.end_session(session_id)

# Binary WebSocket endpoint for audio streaming
@app.websocket("/ws/voice-session-binary")
async def voice_session_binary_websocket(websocket: WebSocket):
    """WebSocket endpoint that handles binary audio data"""
    await websocket.accept()

    session_id: Optional[str] = None
    pipeline: Optional[VoicePipeline] = None

    try:
        while True:
            # Accept both text (control) and binary (audio) messages
            data = await websocket.receive()

            if "text" in data:
                # Control message
                msg = json.loads(data["text"])
                msg_type = msg.get("type")

                if msg_type == "start_session":
                    user_id = msg.get("userId")
                    session_id = str(uuid.uuid4())

                    session = session_manager.create_session(session_id, user_id)

                    pipeline = VoicePipeline(
                        session_id=session_id,
                        websocket=websocket,
                        session_manager=session_manager,
                        lead_extractor=lead_extractor,
                        deepgram_api_key=DEEPGRAM_API_KEY,
                        anthropic_api_key=ANTHROPIC_API_KEY,
                        deepgram_model=DEEPGRAM_MODEL,
                        claude_model=CLAUDE_MODEL
                    )

                    await pipeline.start()

                    await websocket.send_json({
                        "type": "session_started",
                        "sessionId": session_id,
                        "websocketUrl": f"ws://localhost:{PORT}/ws/voice-session-binary"
                    })

                elif msg_type == "end_session":
                    if pipeline:
                        await pipeline.stop()
                    break

                elif msg_type == "interrupt":
                    if pipeline:
                        await pipeline.handle_interrupt()

            elif "bytes" in data:
                # Audio chunk from user
                if pipeline:
                    await pipeline.process_audio_chunk(data["bytes"])

    except WebSocketDisconnect:
        print(f"WebSocket disconnected for session {session_id}")
    except Exception as e:
        print(f"Error in binary WebSocket: {e}")
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })
    finally:
        if pipeline:
            await pipeline.cleanup()
        if session_id:
            session_manager.end_session(session_id)

# ==================== Application Startup ====================

if __name__ == "__main__":
    print(f"Starting Voltar AI Voice Agent on port {PORT}")
    print(f"Deepgram API Key: {'✓' if DEEPGRAM_API_KEY else '✗'}")
    print(f"Anthropic API Key: {'✓' if ANTHROPIC_API_KEY else '✗'}")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=True
    )
