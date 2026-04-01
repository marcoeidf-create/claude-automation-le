"""
Web research module.

For each non-responding prospect, runs targeted Tavily searches to find:
  - Who owns the email / their identity and title
  - Personal background and career history
  - Their agency's size, jurisdiction, and recent activity
  - ORC / organized retail crime incidents or retail theft news in their area
  - Recent grants, budgets, or funding their department received
  - Public statements, press releases, or interviews for communication style
"""

import os
import time
from typing import Optional

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None


def _search(client, query: str, max_results: int = 4) -> list:
    try:
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
        )
        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:600],
            })
        return results
    except Exception as e:
        print(f"    Search warning: {e}")
        return []


def research_prospect(
    email: str,
    name: str,
    agency: str,
    jurisdiction: str,
) -> dict:
    """
    Run a battery of web searches for a prospect and return all findings as
    a structured dict keyed by research category.

    Returns a dict with these keys:
        identity       — who owns this email, their real name and title
        background     — career history, bio, LinkedIn
        orc_news       — ORC/retail theft activity in their jurisdiction
        grants_budget  — recent department funding, grants, budget news
        statements     — press releases, interviews, public statements
        agency_info    — agency size, recent news, major initiatives
    """
    api_key = os.environ.get("TAVILY_API_KEY")

    if not api_key:
        return {"error": "TAVILY_API_KEY not set in environment"}

    if TavilyClient is None:
        return {"error": "tavily-python package not installed — run: pip install tavily-python"}

    client = TavilyClient(api_key=api_key)

    jurisdiction_label = jurisdiction or _jurisdiction_from_email(email)
    name_label = name or "law enforcement"
    agency_label = agency or "police department"

    # Extract domain for identity search
    email_domain = email.split("@")[-1] if "@" in email else ""

    research = {}

    # ── 0. Identity lookup — who owns this email ──────────────────────────────
    identity_results = []
    if email_domain:
        identity_results.extend(_search(
            client,
            f'site:{email_domain} chief sheriff director leadership staff',
            max_results=3,
        ))
        time.sleep(0.3)
    if name_label and name_label != "law enforcement":
        identity_results.extend(_search(
            client,
            f'"{name_label}" {agency_label} title position chief sheriff lieutenant',
            max_results=3,
        ))
        time.sleep(0.3)
    research["identity"] = identity_results

    # ── 1. Personal background ────────────────────────────────────────────────
    research["background"] = _search(
        client,
        f'"{name_label}" {agency_label} biography career history appointed',
    )
    time.sleep(0.3)

    # ── 2. ORC / retail theft — specific and recent ───────────────────────────
    orc_results = []
    if jurisdiction_label:
        orc_results.extend(_search(
            client,
            f"organized retail crime {jurisdiction_label} 2025 2026 arrest bust fencing ring",
            max_results=4,
        ))
        time.sleep(0.3)
        orc_results.extend(_search(
            client,
            f"{jurisdiction_label} retail theft shoplifting police investigation 2025 2026",
            max_results=3,
        ))
        time.sleep(0.3)
        orc_results.extend(_search(
            client,
            f"{jurisdiction_label} ORC smash grab theft organized crime case 2025 2026",
            max_results=3,
        ))
        time.sleep(0.3)
    else:
        orc_results.extend(_search(
            client,
            f"{agency_label} organized retail crime investigation arrest 2025 2026",
            max_results=4,
        ))
        time.sleep(0.3)
    research["orc_news"] = orc_results

    # ── 3. Grants, budgets, and funding ──────────────────────────────────────
    research["grants_budget"] = _search(
        client,
        f"{agency_label} {jurisdiction_label or ''} police grant budget funding 2025 2026",
    )
    time.sleep(0.3)

    # ── 4. Public statements and press releases ───────────────────────────────
    research["statements"] = _search(
        client,
        f'"{name_label}" {agency_label} press release statement interview 2025 2026',
    )
    time.sleep(0.3)

    # ── 5. Agency recent activity ─────────────────────────────────────────────
    if jurisdiction_label:
        research["agency_info"] = _search(
            client,
            f"{agency_label} {jurisdiction_label} police department news initiative 2025 2026",
        )
    else:
        research["agency_info"] = []

    return research


def _jurisdiction_from_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    domain = email.split("@")[1].lower().split(".")[0]
    for suffix in ["pd", "police", "sheriff", "so", "co", "city"]:
        domain = domain.replace(suffix, "").strip()
    return domain.title() if len(domain) > 2 else ""
