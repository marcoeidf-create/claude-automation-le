"""
Cluster Forensics — Automated Outreach Intelligence System
==========================================================

Each run does three things in order:
  1. Checks all tracked prospects for new replies (marks hot, removes from queue)
  2. Finds new unanswered sent emails to LE addresses, researches them,
     writes personalized follow-ups, and saves as Gmail Drafts for manual review
  3. Prints a daily briefing

Drafts are never sent automatically. Review and send from Gmail Drafts.

Usage:
    python run.py

Requirements:
    - .env file with GOOGLE_API_KEY and TAVILY_API_KEY
    - credentials.json from Google Cloud Console (Gmail API OAuth2)
    - pip install -r requirements.txt
"""

import os
import re
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from src.gmail_client import (
    get_gmail_service,
    get_unanswered_sent_emails,
    check_for_replies,
    save_draft,
)
from src.prospect_parser import parse_prospect_from_email
from src.researcher import research_prospect
from src.profile_builder import build_profile
from src.email_writer import write_followup_email
from src.scheduler import get_timezone_for_jurisdiction, get_next_send_window, format_send_time
from src.tracker import ProspectTracker
from src.briefing import print_briefing

# Statuses that mean "do not create a new draft for this prospect"
_TERMINAL_STATUSES = {"draft_ready", "sent", "replied", "meeting_booked", "cancelled"}

# Domains to never process — internal, partner, own company
_BLOCKED_DOMAINS = {"datacluster.com", "algopix.com", "clusterforensics.com"}

# First names to never process — internal team / known contacts
_BLOCKED_NAMES = {"joy", "jyo", "gil", "shannon", "tadas"}

# TLDs and domain keywords that identify legitimate LE / government email addresses.
# Anything that doesn't match is skipped — we only want to reach actual LE agencies.
_ALLOWED_TLDS = {".gov", ".us"}
_LE_DOMAIN_KEYWORDS = {
    "police", "sheriff", "constable", "marshal", "trooper",
    "enforcement", "corrections", "dept", "pd", "sheriff",
}


def _extract_email_address(to_field: str) -> str:
    """Extract bare email address from a 'Name <email@domain>' string."""
    if "<" in to_field and ">" in to_field:
        return to_field.split("<")[1].split(">")[0].strip()
    return to_field.strip()


def _is_le_domain(email_addr: str) -> bool:
    """
    Return True only if the email domain looks like a legitimate LE or
    government address.

    Passes:
      - Any .gov or .us TLD  (e.g. chief@austin.gov, jane@houstontx.gov)
      - Any domain containing an LE keyword  (e.g. john@austinpd.org,
        info@sheriffoffice.net, chief@police.cityname.com)

    Blocks everything else — commercial .com/.net/.io/.co addresses with
    no LE keyword are not prospects.
    """
    if "@" not in email_addr:
        return False
    domain = email_addr.split("@")[-1].lower().strip()

    # Check TLD
    for tld in _ALLOWED_TLDS:
        if domain.endswith(tld):
            return True

    # Check for LE keyword anywhere in the domain
    for keyword in _LE_DOMAIN_KEYWORDS:
        if keyword in domain:
            return True

    return False


def _is_blocked(email_addr: str, to_field: str = "") -> bool:
    """Return True if this address is explicitly blocked by domain or name."""
    if "@" in email_addr:
        domain = email_addr.split("@")[-1].lower().strip()
        if domain in _BLOCKED_DOMAINS:
            return True

    local_part = email_addr.split("@")[0].lower() if "@" in email_addr else email_addr.lower()
    display_name = to_field.split("<")[0].strip().lower() if "<" in to_field else ""

    for blocked in _BLOCKED_NAMES:
        for s in [local_part, display_name]:
            if re.search(rf"\b{re.escape(blocked)}\b", s):
                return True

    return False


def _validate_env():
    """Abort early if required environment variables are missing."""
    missing = []
    if not os.environ.get("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")
    if not os.environ.get("TAVILY_API_KEY"):
        missing.append("TAVILY_API_KEY")
    if missing:
        print("ERROR: Missing required environment variables:")
        for var in missing:
            print(f"  {var}")
        print("\nCreate a .env file based on .env.example and fill in your API keys.")
        sys.exit(1)


def _check_and_update_replies(service, tracker) -> list:
    """
    Check all tracked prospects for new replies.

    Marks newly replied prospects as 'replied' (Hot) so they appear in the
    briefing and are excluded from future draft creation.
    """
    all_prospects = tracker.all_prospects()
    newly_replied = check_for_replies(service, all_prospects)

    if newly_replied:
        print(f"  {len(newly_replied)} new repl{'y' if len(newly_replied) == 1 else 'ies'} detected")

    for prospect in newly_replied:
        email_addr = prospect.get("email", "")
        name = prospect.get("name") or email_addr
        print(f"  → REPLY from {name} — moving to Hot queue")
        tracker.upsert_prospect(email_addr, {"status": "replied"})

    if newly_replied:
        tracker.save()

    return newly_replied


def main():
    print()
    print("=" * 62)
    print("  CLUSTER FORENSICS — OUTREACH INTELLIGENCE SYSTEM")
    print("=" * 62)

    _validate_env()

    days_threshold = int(os.environ.get("DAYS_THRESHOLD", "7"))

    # ── Load CRM ──────────────────────────────────────────────────────────────
    tracker = ProspectTracker()
    print(f"\n  Loaded {len(tracker.all_prospects())} existing prospect records")

    # ── Connect to Gmail ──────────────────────────────────────────────────────
    print("\n  Connecting to Gmail...")
    try:
        service = get_gmail_service()
        print("  Gmail connected")
    except FileNotFoundError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR connecting to Gmail: {e}")
        sys.exit(1)

    # ── Pass 1: Check for replies on tracked prospects ────────────────────────
    print("\n  Checking tracked prospects for replies...")
    newly_replied = _check_and_update_replies(service, tracker)
    if not newly_replied:
        print("  No new replies")

    # ── Pass 2: Find and process new unanswered sent emails ───────────────────
    print(f"\n  Scanning for sent emails with no reply ({days_threshold}+ days)...")
    try:
        unanswered = get_unanswered_sent_emails(service, days_threshold=days_threshold)
    except Exception as e:
        print(f"\nERROR reading sent folder: {e}")
        sys.exit(1)

    # Filter: LE domains only, not blocked, not already handled
    skipped_non_le = 0
    skipped_blocked = 0
    skipped_done = 0
    to_process = []

    for email_data in unanswered:
        to_field = email_data.get("to", "")
        email_addr = _extract_email_address(to_field)

        if _is_blocked(email_addr, to_field):
            skipped_blocked += 1
            continue

        if not _is_le_domain(email_addr):
            skipped_non_le += 1
            continue

        existing = tracker.get_prospect(email_addr)
        if existing and existing.get("status") in _TERMINAL_STATUSES:
            skipped_done += 1
            continue

        to_process.append(email_data)

    print(f"  {len(to_process)} LE prospects to process  "
          f"({skipped_non_le} non-LE skipped, {skipped_blocked} blocked, "
          f"{skipped_done} already handled)")

    if not to_process:
        print("\n  Nothing new to process.")
        print_briefing(tracker, [], newly_replied=newly_replied)
        return

    newly_processed = []

    for i, email_data in enumerate(to_process, start=1):
        to_field = email_data.get("to", "")
        email_addr = _extract_email_address(to_field)

        print(f"\n  [{i}/{len(to_process)}] {to_field or email_addr}")

        # ── Parse prospect info ───────────────────────────────────────────────
        print("    → Parsing prospect info...")
        try:
            prospect_info = parse_prospect_from_email(email_data)
        except Exception as e:
            print(f"    → Parse error: {e} — skipping")
            continue

        if not prospect_info:
            print("    → Could not parse prospect info — skipping")
            continue

        prospect_info.update({
            "email": email_addr,
            "to_raw": to_field,
            "sent_date": email_data.get("sent_date", ""),
            "days_since_sent": email_data.get("days_since_sent", 0),
            "original_subject": email_data.get("subject", ""),
            "original_body": email_data.get("body", ""),
            "thread_id": email_data.get("thread_id", ""),
        })

        tracker.upsert_prospect(email_addr, prospect_info)
        tracker.save()

        name_display = prospect_info.get("name") or email_addr
        agency_display = prospect_info.get("agency") or "(agency unknown)"
        title_display = prospect_info.get("title") or ""
        print(f"    → {title_display} {name_display}, {agency_display}".strip())

        # ── Determine timezone / suggested send window (informational only) ───
        try:
            tz_str = get_timezone_for_jurisdiction(
                prospect_info.get("jurisdiction", ""),
                prospect_info.get("agency", ""),
            )
            suggested_utc = get_next_send_window(tz_str)
            send_display = format_send_time(suggested_utc, tz_str)
            tracker.upsert_prospect(email_addr, {
                "prospect_timezone": tz_str,
                "suggested_send_time": suggested_utc.isoformat(),
            })
            tracker.save()
        except Exception as e:
            print(f"    → Timezone error: {e} — defaulting to America/New_York")
            tz_str = "America/New_York"
            suggested_utc = get_next_send_window(tz_str)
            send_display = format_send_time(suggested_utc, tz_str)
            tracker.upsert_prospect(email_addr, {
                "prospect_timezone": tz_str,
                "suggested_send_time": suggested_utc.isoformat(),
            })
            tracker.save()

        # ── Research ──────────────────────────────────────────────────────────
        print("    → Researching via web search...")
        try:
            research = research_prospect(
                email=email_addr,
                name=prospect_info.get("name", ""),
                agency=prospect_info.get("agency", ""),
                jurisdiction=prospect_info.get("jurisdiction", ""),
            )
            tracker.upsert_prospect(email_addr, {"research": research})
            tracker.save()
        except Exception as e:
            print(f"    → Research error: {e} — continuing with available data")
            research = {}

        # ── Build profile ─────────────────────────────────────────────────────
        print("    → Building strategic profile...")
        try:
            profile = build_profile(prospect_info, research)
            tracker.upsert_prospect(email_addr, {"profile": profile})
            tracker.save()
            angle = profile.get("recommended_angle", "unknown").replace("_", " ").title()
            print(f"    → Angle: {angle}")
            if profile.get("local_news_hook"):
                print(f"    → News hook found")
        except Exception as e:
            print(f"    → Profile build error: {e} — using defaults")
            profile = {}

        # ── Write email ───────────────────────────────────────────────────────
        print("    → Writing personalized follow-up email...")
        try:
            subject, body = write_followup_email(
                prospect=prospect_info,
                profile=profile,
                original_email_body=email_data.get("body", ""),
            )
            tracker.upsert_prospect(email_addr, {
                "followup_email": {"subject": subject, "body": body},
            })
            tracker.save()
        except Exception as e:
            print(f"    → Email write error: {e} — skipping draft save")
            tracker.upsert_prospect(email_addr, {"status": "write_failed"})
            tracker.save()
            continue

        # ── Save draft ────────────────────────────────────────────────────────
        print("    → Saving draft to Gmail...")
        try:
            draft_id = save_draft(service, email_addr, subject, body)
        except Exception as e:
            print(f"    → Draft save error: {e}")
            draft_id = None

        if draft_id:
            tracker.upsert_prospect(email_addr, {
                "draft_saved": True,
                "draft_id": draft_id,
                "status": "draft_ready",
            })
            print(f"    → Draft saved. Suggested send: {send_display}")
        else:
            tracker.upsert_prospect(email_addr, {
                "draft_saved": False,
                "draft_id": None,
                "status": "draft_failed",
            })
            print("    → Draft save failed — content in prospects.json")

        tracker.save()
        newly_processed.append(email_addr)

    # ── Final save and briefing ───────────────────────────────────────────────
    tracker.save()
    print_briefing(tracker, newly_processed, newly_replied=newly_replied)


if __name__ == "__main__":
    main()
