"""
Lead Extractor - Extract and qualify leads from conversations
Uses pattern matching and NLP to identify contact info and pain points
"""

import re
import json
from typing import Dict, List, Optional
from datetime import datetime


class LeadExtractor:
    """Extracts lead information from conversation transcripts"""

    def __init__(self):
        self.leads: Dict[str, dict] = {}
        self.session_leads: Dict[str, dict] = {}  # session_id -> partial lead data

        # Regex patterns for extraction
        self.email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        self.phone_pattern = re.compile(r'\b(\+?1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b')

        # Common pain point keywords
        self.pain_point_keywords = [
            "problem", "issue", "challenge", "difficult", "struggling",
            "frustrated", "expensive", "slow", "manual", "time-consuming",
            "inefficient", "error", "mistake", "losing", "missing",
            "overwhelmed", "complicated", "confusing", "hard to"
        ]

    async def extract_from_text(
        self,
        session_id: str,
        text: str,
        conversation_history: List[dict]
    ):
        """Extract lead information from a text message"""
        if session_id not in self.session_leads:
            self.session_leads[session_id] = {
                "name": None,
                "email": None,
                "phone": None,
                "pain_points": [],
                "interest_signals": []
            }

        lead_data = self.session_leads[session_id]

        # Extract email
        emails = self.email_pattern.findall(text)
        if emails and not lead_data["email"]:
            lead_data["email"] = emails[0]
            print(f"[{session_id}] Extracted email: {emails[0]}")

        # Extract phone
        phones = self.phone_pattern.findall(text)
        if phones and not lead_data["phone"]:
            # Clean up phone number
            phone = ''.join(filter(str.isdigit, str(phones[0])))
            lead_data["phone"] = phone
            print(f"[{session_id}] Extracted phone: {phone}")

        # Extract name (simple heuristic - look for "I'm X" or "My name is X")
        name_patterns = [
            r"(?:I'm|I am|my name is|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:here|speaking)"
        ]

        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match and not lead_data["name"]:
                lead_data["name"] = match.group(1).title()
                print(f"[{session_id}] Extracted name: {lead_data['name']}")
                break

        # Extract pain points
        text_lower = text.lower()
        for keyword in self.pain_point_keywords:
            if keyword in text_lower:
                # Extract sentence containing the keyword
                sentences = text.split('.')
                for sentence in sentences:
                    if keyword in sentence.lower():
                        pain_point = sentence.strip()
                        if pain_point and pain_point not in lead_data["pain_points"]:
                            lead_data["pain_points"].append(pain_point)
                            print(f"[{session_id}] Extracted pain point: {pain_point}")

        # Detect interest signals
        interest_keywords = [
            "interested", "want to", "would like", "sounds good",
            "tell me more", "how does", "pricing", "cost", "demo",
            "trial", "sign up", "get started"
        ]

        for keyword in interest_keywords:
            if keyword in text_lower:
                if keyword not in lead_data["interest_signals"]:
                    lead_data["interest_signals"].append(keyword)

    def get_session_lead_data(self, session_id: str) -> Optional[dict]:
        """Get extracted lead data for a session"""
        return self.session_leads.get(session_id)

    def calculate_qualification_score(
        self,
        interest_level: str,
        pain_points: List[str],
        has_contact: bool
    ) -> int:
        """
        Calculate lead qualification score (0-100)

        Scoring:
        - Interest level: high=40, medium=25, low=10
        - Pain points: 5 per point (max 30)
        - Contact info: 30
        """
        score = 0

        # Interest level
        interest_scores = {"high": 40, "medium": 25, "low": 10}
        score += interest_scores.get(interest_level.lower(), 10)

        # Pain points (max 30 points)
        score += min(len(pain_points) * 5, 30)

        # Contact info
        if has_contact:
            score += 30

        return min(score, 100)

    def infer_interest_level(self, session_id: str) -> str:
        """Infer interest level from conversation signals"""
        lead_data = self.session_leads.get(session_id)
        if not lead_data:
            return "low"

        signals = lead_data.get("interest_signals", [])

        # High interest signals
        high_signals = ["pricing", "cost", "demo", "trial", "sign up", "get started"]
        if any(sig in signals for sig in high_signals):
            return "high"

        # Medium interest signals
        medium_signals = ["interested", "tell me more", "how does"]
        if any(sig in signals for sig in medium_signals):
            return "medium"

        return "low"

    def save_lead(self, lead_data: dict):
        """Save lead data"""
        lead_id = lead_data.get("lead_id")
        if lead_id:
            self.leads[lead_id] = lead_data
            print(f"Saved lead: {lead_id} (score: {lead_data.get('qualification_score')})")

    def get_lead(self, lead_id: str) -> Optional[dict]:
        """Get lead by ID"""
        return self.leads.get(lead_id)

    def get_all_leads(self) -> List[dict]:
        """Get all saved leads"""
        return list(self.leads.values())

    def get_qualified_leads(self, min_score: int = 50) -> List[dict]:
        """Get leads above a qualification threshold"""
        return [
            lead for lead in self.leads.values()
            if lead.get("qualification_score", 0) >= min_score
        ]

    def export_leads_json(self, filepath: str):
        """Export leads to JSON file"""
        with open(filepath, 'w') as f:
            json.dump(list(self.leads.values()), f, indent=2)
        print(f"Exported {len(self.leads)} leads to {filepath}")

    def get_lead_stats(self) -> dict:
        """Get lead statistics"""
        total_leads = len(self.leads)
        if total_leads == 0:
            return {
                "total_leads": 0,
                "avg_score": 0,
                "high_quality": 0,
                "medium_quality": 0,
                "low_quality": 0
            }

        scores = [lead.get("qualification_score", 0) for lead in self.leads.values()]
        avg_score = sum(scores) / len(scores)

        high_quality = sum(1 for s in scores if s >= 70)
        medium_quality = sum(1 for s in scores if 40 <= s < 70)
        low_quality = sum(1 for s in scores if s < 40)

        return {
            "total_leads": total_leads,
            "avg_score": int(avg_score),
            "high_quality": high_quality,
            "medium_quality": medium_quality,
            "low_quality": low_quality
        }
