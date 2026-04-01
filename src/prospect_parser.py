"""
Extracts structured prospect information from raw outbound email data.

Uses Gemini to parse the recipient's name, title, agency, and jurisdiction
from the To: field, Subject, and email body.
"""

import json
import os
from typing import Optional

from google import genai


def _get_client():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not set in environment")
    return genai.Client(api_key=api_key)


def parse_prospect_from_email(email_data: dict) -> Optional[dict]:
    """
    Extract structured prospect info from a raw outbound email dict.

    Returns a dict with: name, first_name, title, agency, jurisdiction
    Returns None if extraction fails entirely.
    """
    to_field = email_data.get("to", "")
    subject = email_data.get("subject", "")
    body = email_data.get("body", "")[:2000]

    def name_from_to_field(to: str) -> str:
        if "<" in to:
            candidate = to.split("<")[0].strip().strip('"').strip("'")
            if candidate:
                return candidate
        return to.strip()

    prompt = f"""You are parsing a B2B outreach email to a Law Enforcement executive.
Extract structured information about the recipient.

TO: {to_field}
SUBJECT: {subject}
EMAIL BODY (first portion):
{body}

Extract and return a JSON object with these exact keys:
- "name": Full name of the recipient
- "first_name": First name only
- "title": Their law enforcement title (e.g., "Chief of Police", "Sheriff", "Lieutenant")
- "agency": Name of their law enforcement agency or department
- "jurisdiction": The city, county, or region they serve (e.g., "Austin, TX")

Rules:
- If a field cannot be determined confidently, use null
- Do not guess or fabricate information
- Return ONLY valid JSON — no markdown, no explanation, no extra text"""

    try:
        client = _get_client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        return json.loads(text)

    except json.JSONDecodeError as e:
        print(f"  Warning: JSON parse error from Gemini — {e}")
    except Exception as e:
        print(f"  Warning: error in prospect parser — {e}")

    fallback_name = name_from_to_field(to_field)
    return {
        "name": fallback_name,
        "first_name": fallback_name.split()[0] if fallback_name else None,
        "title": None,
        "agency": None,
        "jurisdiction": None,
    }
