"""
Session Manager - Track and manage voice session state
"""

from typing import Dict, Optional, List
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class Session:
    """Represents a voice session"""
    session_id: str
    user_id: Optional[str] = None
    status: str = "active"  # active, ended
    created_at: datetime = field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    messages: List[dict] = field(default_factory=list)
    lead_captured: bool = False
    metadata: Dict = field(default_factory=dict)

    def add_message(self, role: str, text: str):
        """Add a message to the session transcript"""
        self.messages.append({
            "role": role,
            "text": text,
            "timestamp": int(datetime.utcnow().timestamp() * 1000)
        })

    def get_duration(self) -> int:
        """Get session duration in seconds"""
        if self.ended_at:
            return int((self.ended_at - self.created_at).total_seconds())
        return int((datetime.utcnow() - self.created_at).total_seconds())

    def end(self):
        """End the session"""
        self.status = "ended"
        self.ended_at = datetime.utcnow()


class SessionManager:
    """Manages all active and past sessions"""

    def __init__(self):
        self.sessions: Dict[str, Session] = {}

    def create_session(self, session_id: str, user_id: Optional[str] = None) -> Session:
        """Create a new session"""
        session = Session(session_id=session_id, user_id=user_id)
        self.sessions[session_id] = session
        print(f"Created session: {session_id}")
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID"""
        return self.sessions.get(session_id)

    def end_session(self, session_id: str):
        """End a session"""
        session = self.get_session(session_id)
        if session:
            session.end()
            print(f"Ended session: {session_id} (duration: {session.get_duration()}s)")

    def get_active_sessions(self) -> List[Session]:
        """Get all active sessions"""
        return [s for s in self.sessions.values() if s.status == "active"]

    def cleanup_old_sessions(self, max_age_hours: int = 24):
        """Remove sessions older than max_age_hours"""
        cutoff = datetime.utcnow().timestamp() - (max_age_hours * 3600)
        to_remove = [
            sid for sid, session in self.sessions.items()
            if session.created_at.timestamp() < cutoff
        ]

        for sid in to_remove:
            del self.sessions[sid]

        if to_remove:
            print(f"Cleaned up {len(to_remove)} old sessions")

    def get_session_stats(self) -> dict:
        """Get overall session statistics"""
        total = len(self.sessions)
        active = len(self.get_active_sessions())
        ended = total - active

        avg_duration = 0
        if self.sessions:
            avg_duration = sum(s.get_duration() for s in self.sessions.values()) / total

        leads_captured = sum(1 for s in self.sessions.values() if s.lead_captured)

        return {
            "total_sessions": total,
            "active_sessions": active,
            "ended_sessions": ended,
            "average_duration": int(avg_duration),
            "leads_captured": leads_captured
        }
