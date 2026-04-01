"""
Lightweight JSON-based CRM for tracking prospect research, profiles,
follow-up status, and draft history between runs.
"""

import json
import os
from datetime import datetime
from typing import Optional

TRACKER_FILE = "prospects.json"


class ProspectTracker:
    def __init__(self, filepath: str = TRACKER_FILE):
        self.filepath = filepath
        self.data = self._load()

    def _load(self) -> dict:
        """Load existing tracker data from disk, or initialize fresh."""
        if os.path.exists(self.filepath):
            with open(self.filepath, "r") as f:
                return json.load(f)
        return {
            "prospects": {},
            "last_run": None,
        }

    def save(self):
        """Persist current tracker state to disk."""
        self.data["last_run"] = datetime.now().isoformat()
        with open(self.filepath, "w") as f:
            json.dump(self.data, f, indent=2, default=str)

    def get_prospect(self, email: str) -> Optional[dict]:
        """Retrieve a prospect record by email address."""
        return self.data["prospects"].get(email)

    def upsert_prospect(self, email: str, updates: dict):
        """
        Insert or update a prospect record. Merges `updates` into the
        existing record so partial updates don't overwrite prior data.
        """
        if email not in self.data["prospects"]:
            self.data["prospects"][email] = {
                "email": email,
                "created_at": datetime.now().isoformat(),
                "status": "pending_research",
            }
        self.data["prospects"][email].update(updates)
        self.data["prospects"][email]["updated_at"] = datetime.now().isoformat()

    def all_prospects(self) -> list:
        """Return all tracked prospects as a list."""
        return list(self.data["prospects"].values())

    def mark_draft_sent(self, email: str):
        """Mark a prospect's draft as manually sent (for future tracking)."""
        self.upsert_prospect(email, {"status": "sent", "sent_at": datetime.now().isoformat()})
        self.save()
