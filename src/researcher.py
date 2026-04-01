"""
Web research module.

For each non-responding prospect, runs targeted Tavily searches to find:
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
    TavilyClient = None  # Handled gracefully below


def _search(client, query: str, max_results: int = 4) -> list:
    """
    Execute a single Tavily search and return a list of result dicts.
    Returns an empty list on any error so one bad search doesn't stop the run.
    """
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
                # Truncate content to ~600 chars to keep token usage reasonable
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

    # Build search terms; fall back to email domain if fields are missing
    jurisdiction_label = jurisdiction or _jurisdiction_from_email(email)
    name_label = name or "law enforcement"
    agency_label = agency or "police department"

    research = {}

    # ── 1. Personal background ─────────────────────────────────────────────────
    research["background"] = _search(
        client,
        f'"{name_label}" {agency_label} chief police sheriff biography career',
    )
    time.sleep(0.3)  # Respect rate limits

    # ── 2. ORC / retail theft activity in their jurisdiction ──────────────────
    orc_queries = []
    if jurisdiction_label:
        orc_queries.append(
            f"organized retail crime theft {jurisdiction_label} 2024 2025 arrest fencing"
        )
        orc_queries.append(
            f"{jurisdiction_label} retail theft ORC police investigation 2024 2025"
        )
    else:
        orc_queries.append(
            f"{agency_label} organized retail crime investigation 2024 2025"
        )

    orc_results = []
    for q in orc_queries:
        orc_results.extend(_search(client, q, max_results=3))
        time.sleep(0.3)
    research["orc_news"] = orc_results

    # ── 3. Grants, budgets, and funding ───────────────────────────────────────
    research["grants_budget"] = _search(
        client,
        f"{agency_label} {jurisdiction_label or ''} police grant budget funding 2024 2025",
    )
    time.sleep(0.3)

    # ── 4. Public statements and press releases ───────────────────────────────
    research["statements"] = _search(
        client,
        f'"{name_label}" police chief sheriff press release statement interview 2024 2025',
    )
    time.sleep(0.3)

    # ── 5. Agency recent activity ─────────────────────────────────────────────
    if jurisdiction_label:
        research["agency_info"] = _search(
            client,
            f"{agency_label} {jurisdiction_label} police department news 2024 2025",
        )
    else:
        research["agency_info"] = []

    return research


def _jurisdiction_from_email(email: str) -> str:
    """
    Heuristic: attempt to extract a jurisdiction hint from an email domain.
    e.g. john@austinpd.gov → "Austin"
    Returns empty string if nothing useful found.
    """
    if not email or "@" not in email:
        return ""
    domain = email.split("@")[1].lower().split(".")[0]
    # Strip common LE suffixes
    for suffix in ["pd", "police", "sheriff", "so", "co", "city"]:
        domain = domain.replace(suffix, "").strip()
    return domain.title() if len(domain) > 2 else ""
