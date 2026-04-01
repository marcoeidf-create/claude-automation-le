"""
Terminal briefing output.

Prints a daily summary showing:
- Hot prospects (replied but no meeting booked yet)
- Drafts ready for manual review with suggested send time
- Strong local news hooks
- Any draft save failures
"""

from datetime import datetime


def print_briefing(
    tracker,
    newly_processed: list,
    sent_this_run: list = None,
    newly_replied: list = None,
):
    """
    Print the daily intelligence briefing to stdout.

    Args:
        tracker:          ProspectTracker with current state
        newly_processed:  Email addresses processed (new drafts created) this run
        sent_this_run:    Email addresses whose drafts were auto-sent this run
        newly_replied:    Email addresses that replied since last run
    """
    sent_this_run = sent_this_run or []
    newly_replied = newly_replied or []

    prospects = tracker.all_prospects()
    draft_ready = [p for p in prospects if p.get("status") == "draft_ready"]
    hot = [p for p in prospects if p.get("status") == "replied"]
    draft_failed = [p for p in prospects if p.get("status") == "draft_failed"]
    sent_all = [p for p in prospects if p.get("status") in {"sent", "meeting_booked"}]
    strong_hooks = [p for p in draft_ready if p.get("profile", {}).get("local_news_hook")]

    _div = "─" * 62

    print()
    print("=" * 62)
    print("  CLUSTER FORENSICS — OUTREACH INTELLIGENCE BRIEFING")
    print(f"  {datetime.now().strftime('%B %d, %Y  %I:%M %p')}")
    print("=" * 62)

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("  SUMMARY")
    print(f"  {'Total prospects tracked:':<36} {len(prospects)}")
    print(f"  {'Drafts ready for review:':<36} {len(draft_ready)}")
    print(f"  {'Sent / meeting booked all-time:':<36} {len(sent_all)}")
    print(f"  {'New drafts created this run:':<36} {len(newly_processed)}")
    if hot:
        print(f"  {'HOT — replied, no meeting yet:':<36} {len(hot)}")
    if draft_failed:
        print(f"  {'Draft save failures:':<36} {len(draft_failed)}")

    # ── Hot prospects ─────────────────────────────────────────────────────────
    if hot:
        print()
        print(_div)
        print(f"  HOT — REPLIED BUT NO MEETING BOOKED ({len(hot)})")
        print("  These people responded. Prioritize them manually.")
        print(_div)
        for p in hot:
            name = _display_name(p)
            agency = p.get("agency") or "Unknown Agency"
            email_addr = p.get("email", "")
            days = p.get("days_since_sent", "?")
            print(f"\n  {name}  |  {agency}")
            print(f"  Email: {email_addr}")
            print(f"  Original outreach: {days} days ago")
            print(f"  Action needed: Reply detected. Book the meeting.")

    # ── Strong news hooks ─────────────────────────────────────────────────────
    if strong_hooks:
        print()
        print(_div)
        print(f"  STRONG LOCAL NEWS HOOKS — REVIEW THESE FIRST ({len(strong_hooks)})")
        print(_div)
        for p in strong_hooks:
            name = _display_name(p)
            hook = p.get("profile", {}).get("local_news_hook", "")
            send_display = _format_send_display(p)
            print(f"\n  {name}")
            print(f"  Hook:   {_wrap(hook, width=54, indent=10)}")
            if send_display:
                print(f"  Suggest: {send_display}")

    # ── Drafts ready for review ───────────────────────────────────────────────
    if draft_ready:
        print()
        print(_div)
        print(f"  DRAFTS READY FOR REVIEW ({len(draft_ready)})")
        print("  Review in Gmail Drafts. Suggested send times shown below.")
        print(_div)

        for p in draft_ready:
            profile = p.get("profile", {})
            followup = p.get("followup_email", {})
            name = _display_name(p)
            agency = p.get("agency") or "Unknown Agency"
            angle = profile.get("recommended_angle", "unknown").replace("_", " ").title()
            rationale = profile.get("angle_rationale", "")
            hook = profile.get("local_news_hook")
            days = p.get("days_since_sent", "?")
            orc = profile.get("orc_activity_summary", "")
            subject = followup.get("subject", "")
            send_display = _format_send_display(p)

            print(f"\n  {name}  |  {agency}")
            print(f"  Email:   {p.get('email', '')}")
            print(f"  Silent:  {days} days")
            if send_display:
                print(f"  Suggest: {send_display}")
            print(f"  Angle:   {angle}")
            if rationale:
                print(f"  Why:     {_wrap(rationale, width=54, indent=11)}")
            if hook:
                print(f"  Hook:    {_wrap(hook, width=54, indent=11)}")
            if orc and orc != "No specific ORC incidents found in research.":
                print(f"  ORC:     {_wrap(orc, width=54, indent=11)}")
            if subject:
                print(f"  Subject: \"{subject}\"")

    # ── Failures ──────────────────────────────────────────────────────────────
    if draft_failed:
        print()
        print(_div)
        print("  DRAFT SAVE FAILURES — email content stored in prospects.json")
        print(_div)
        for p in draft_failed:
            print(f"  {_display_name(p)}  <{p.get('email', '')}>")

    print()
    print("=" * 62)
    print("  Review drafts:  Gmail → Drafts")
    print("  Prospect data:  ./prospects.json")
    print("=" * 62)
    print()


def _display_name(prospect: dict) -> str:
    """Return 'Title Name' or just name."""
    title = prospect.get("title", "")
    name = prospect.get("name", prospect.get("email", "Unknown"))
    if title and name and title not in name:
        return f"{title} {name}"
    return name


def _format_send_display(prospect: dict) -> str:
    """Return a formatted scheduled send time string, or empty string."""
    from src.scheduler import format_send_time
    scheduled_str = prospect.get("suggested_send_time")
    tz_str = prospect.get("prospect_timezone", "America/New_York")
    if not scheduled_str:
        return ""
    try:
        from datetime import timezone
        utc_dt = datetime.fromisoformat(scheduled_str)
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        return format_send_time(utc_dt, tz_str)
    except Exception:
        return scheduled_str


def _wrap(text: str, width: int = 58, indent: int = 0) -> str:
    """Simple word-wrap; subsequent lines indented by `indent` spaces."""
    if not text or len(text) <= width:
        return text
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= width:
            current = f"{current} {word}".strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    pad = " " * indent
    return f"\n{pad}".join(lines)
