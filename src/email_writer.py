"""
Personalized follow-up email writer.

Uses Gemini 2.0 Flash with the full writing style guide injected as a
system instruction on every single call.
"""

import os
from typing import Tuple

from google import genai
from google.genai import types

# ── Writing style system instruction ──────────────────────────────────────────
# Injected verbatim as a Gemini system instruction on every call.
WRITING_STYLE_SYSTEM_PROMPT = """VOICE & TONE
Write like a smart person talking to another smart person. No fluff, no filler, no corporate speak. Do not over-explain things the reader already knows. Assume intelligence. Match the energy of the recipient — if they are direct and formal, be direct and formal.
Never use words like "certainly," "absolutely," "great question," or "of course." Those are filler words that add zero meaning and signal that a bot is talking, not a person.

SENTENCE STRUCTURE
Use short sentences when making a strong point. Then back it up with a longer one that adds context or nuance. Then short again to land it.
Vary rhythm deliberately. Long sentence that builds context and gives the reader everything they need to understand the situation. Short landing. That contrast creates emphasis without bold text or exclamation marks.
Never stack adjectives. One strong word beats three weak ones. "Prosecution-ready evidence package" not "comprehensive, detailed, professional evidence package."

HOW TO THINK BEFORE WRITING
Before writing anything ask: what does this person actually need to feel or understand after reading this? Not what do I want to say — what do THEY need to receive.
Then ask: what is the single most important thing? Lead with that. Everything else supports it. Never bury the point.
Then ask: what is the resistance? What objection, doubt, or friction exists in the reader's mind right now? Address it directly instead of pretending it does not exist.

WHAT TO NEVER DO
- Never use exclamation marks unless the situation genuinely calls for excitement
- Never use passive voice ("it was decided" → "we decided")
- Never use hedge words when confident ("I think maybe this could potentially work" → "this works")
- Never list things that should be prose — only use bullets when the reader needs to scan, not when organizing thoughts
- Never repeat the question back before answering it
- Never summarize at the end of a response
- Never use "in conclusion" or "to summarize" or "as I mentioned"
- Never start consecutive sentences with the same word

PERSUASION LOGIC
Use this exact structure for every email:
1. Anchor in their reality — something they already know or feel is true
2. Introduce the tension — the gap between where they are and where they want to be
3. Make the logical connection — here is how A leads to B
4. The ask — one thing, specific, low friction

Never persuade by listing features. Persuade by making the reader feel the problem first, then offer the solution.

The reader is a senior law enforcement executive — Chief of Police, Sheriff, or Lieutenant. They are intelligent, busy, skeptical of vendors, and have seen every pitch. They do not respond to enthusiasm. They respond to specificity, relevance, and evidence. Earn their attention by knowing their world better than they expect you to."""

_CF_CONTEXT = """
Cluster Forensics is a forensic intelligence company that sells to Law Enforcement agencies.
We identify Amazon and online marketplace fencing networks tied to organized retail crime (ORC)
in specific jurisdictions. We produce prosecution-ready evidence packages showing exactly which
stolen goods from local retailers are being fenced online, and by whom. Our "cluster map" shows
the entire ORC network operating in a department's area — connections between boosters, fences,
and online sellers that most departments have never been able to visualize. The ask is always a
15-minute call to walk through the cluster map for their specific jurisdiction.
"""


def _get_client():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not set in environment")
    return genai.Client(api_key=api_key)


def write_followup_email(
    prospect: dict,
    profile: dict,
    original_email_body: str,
) -> Tuple[str, str]:
    """
    Write a personalized follow-up email. Returns (subject, body).
    """
    original_snippet = original_email_body[:800].strip() if original_email_body else "(not available)"

    angle_descriptions = {
        "data_driven": "Focus on evidence quality, clearance rates, and the prosecutorial value of our intelligence.",
        "community_safety": "Lead with the visible retail theft problem in their community and the pressure departments face to act on it.",
        "career_political": "Frame this around legacy, reputation, and the political win of cracking a major ORC network.",
        "budget_grant_roi": "Tie this to ROI on existing grants, show how our product multiplies the impact of their budget.",
    }

    tone_descriptions = {
        "formal_authoritative": "Highly formal. Command respect. Short sentences. No softening language.",
        "data_led": "Lead with a specific data point or finding. Analytical and evidence-focused.",
        "community_focused": "Acknowledge the community impact. Show you understand the department's public accountability.",
        "political_career": "Acknowledge their visibility and the opportunity this represents. Confident, not sycophantic.",
    }

    angle = profile.get("recommended_angle", "data_driven")
    tone = profile.get("recommended_tone", "formal_authoritative")
    hook = profile.get("local_news_hook")
    talking_points = profile.get("key_talking_points", [])
    orc_summary = profile.get("orc_activity_summary", "")

    prompt = f"""You are writing a cold outreach email on behalf of Cluster Forensics to a senior Law Enforcement executive who did not respond to a prior outreach.

COMPANY:
{_CF_CONTEXT.strip()}

RECIPIENT:
- Name: {prospect.get('name') or 'Unknown'}
- First name: {prospect.get('first_name') or (prospect.get('name') or '').split()[0] or 'Unknown'}
- Title: {prospect.get('title') or 'Unknown'}
- Agency: {prospect.get('agency') or 'Unknown'}
- Jurisdiction: {prospect.get('jurisdiction') or 'Unknown'}
- Days since original email: {prospect.get('days_since_sent', 7)}

STRATEGIC PROFILE:
- Angle: {angle_descriptions.get(angle, '')}
- Tone: {tone_descriptions.get(tone, '')}
- Local news hook (if available): {hook or 'None — do not fabricate a hook'}
- ORC context for their area: {orc_summary}
- Key talking points:
{chr(10).join(f'  - {pt}' for pt in talking_points)}

ORIGINAL EMAIL BODY (context only — do NOT quote, reference, or echo it):
{original_snippet}

STRICT RULES:
1. NEVER say: "bumping this", "following up", "circling back", "touching base", "just wanted to", "I hope this finds you well", "reaching out again", or any variation
2. Do NOT acknowledge or reference the prior email
3. If there is a local news hook, open with it — make it the reason you are writing today
4. If no hook, open with a specific factual statement about ORC in their jurisdiction — never generic
5. Connect to Cluster Forensics' value for their department in their area specifically
6. One clear call to action: 15 minutes to walk through the cluster map for their jurisdiction
7. Use their last name with title (e.g., "Chief Smith", "Sheriff Johnson")
8. Length: 150–200 words. No longer.
9. Subject line: specific to them — their jurisdiction or local context. Not "Following up", "Quick question", or anything generic.
10. Sign off as: [Your Name], Cluster Forensics

OUTPUT FORMAT (exact):
Subject: [subject line]

[email body]"""

    try:
        client = _get_client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=WRITING_STYLE_SYSTEM_PROMPT,
            ),
        )
        return _parse_subject_and_body(response.text.strip(), prospect)
    except Exception as e:
        raise RuntimeError(f"Gemini email generation failed: {e}") from e


def _parse_subject_and_body(raw_text: str, prospect: dict) -> Tuple[str, str]:
    subject = ""
    body_lines = []
    found_subject = False
    body_started = False

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not found_subject and stripped.lower().startswith("subject:"):
            subject = stripped[len("subject:"):].strip()
            found_subject = True
            continue
        if found_subject:
            if not body_started and not stripped:
                continue
            body_started = True
            body_lines.append(line)

    body = "\n".join(body_lines).strip()

    if not subject:
        jurisdiction = prospect.get("jurisdiction", "")
        agency = prospect.get("agency", "")
        subject = f"ORC Intelligence — {jurisdiction or agency or 'Your Jurisdiction'}"

    if not body:
        body = raw_text.strip()

    return subject, body
