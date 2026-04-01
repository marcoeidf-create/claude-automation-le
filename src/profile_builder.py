"""
Profile builder.

Feeds raw research results into Gemini to synthesize a strategic profile:
angle, local news hook, tone, talking points.
"""

import json
import os

from google import genai

VALID_ANGLES = {"data_driven", "community_safety", "career_political", "budget_grant_roi"}
VALID_TONES = {"formal_authoritative", "data_led", "community_focused", "political_career"}


def _get_client():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not set in environment")
    return genai.Client(api_key=api_key)


def build_profile(prospect: dict, research: dict) -> dict:
    """
    Synthesize web research into a strategic sales profile using Gemini.
    """
    research_text = json.dumps(research, indent=2)[:6000]

    prompt = f"""You are a strategic B2B sales advisor helping Cluster Forensics reach Law Enforcement executives.

WHAT CLUSTER FORENSICS DOES:
We map Amazon/online fencing networks tied to organized retail crime (ORC) in specific jurisdictions.
We give Law Enforcement prosecution-ready evidence packages showing exactly which stolen goods from
local retailers end up being sold online, and by whom. We provide a "cluster map" of the entire ORC
network operating in their area.

PROSPECT:
- Name: {prospect.get('name') or 'Unknown'}
- Title: {prospect.get('title') or research.get('identity', [{}])[0].get('content', 'Unknown — see identity research below')}
- Agency: {prospect.get('agency') or 'Unknown'}
- Jurisdiction: {prospect.get('jurisdiction') or 'Unknown'}
- Email: {prospect.get('email') or 'Unknown'}
- Days without reply: {prospect.get('days_since_sent') or 'Unknown'}

WEB RESEARCH FINDINGS:
{research_text}

Return a JSON object with these exact keys:

"recommended_angle": one of:
  "data_driven" | "community_safety" | "career_political" | "budget_grant_roi"

"angle_rationale": why this angle fits this person — 1-2 sentences citing specific research

"local_news_hook": a specific timely local event from the research to open with, or null

"recommended_tone": one of:
  "formal_authoritative" | "data_led" | "community_focused" | "political_career"

"key_talking_points": array of exactly 2-3 specific personalized talking points

"background_summary": 2-3 sentences on this person and department

"orc_activity_summary": ORC/retail theft context in their jurisdiction, or exactly:
  "No specific ORC incidents found in research."

Return ONLY valid JSON. No markdown, no preamble, no explanation."""

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

        profile = json.loads(text)

        if profile.get("recommended_angle") not in VALID_ANGLES:
            profile["recommended_angle"] = "data_driven"
        if profile.get("recommended_tone") not in VALID_TONES:
            profile["recommended_tone"] = "formal_authoritative"

        return profile

    except json.JSONDecodeError as e:
        print(f"  Warning: profile JSON parse error — {e}")
        return _fallback_profile(prospect)
    except Exception as e:
        print(f"  Warning: error in profile builder — {e}")
        return _fallback_profile(prospect)


def _fallback_profile(prospect: dict) -> dict:
    return {
        "recommended_angle": "data_driven",
        "angle_rationale": "Default angle — research synthesis unavailable.",
        "local_news_hook": None,
        "recommended_tone": "formal_authoritative",
        "key_talking_points": [
            "Cluster Forensics maps ORC fencing networks in your specific jurisdiction",
            "We deliver prosecution-ready evidence packages tied to local retail theft cases",
            "Our cluster map shows stolen goods from local retailers being sold online",
        ],
        "background_summary": f"Research unavailable for {prospect.get('name', 'this prospect')}.",
        "orc_activity_summary": "No specific ORC incidents found in research.",
    }
