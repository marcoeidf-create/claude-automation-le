"""
Extracts structured prospect information from raw outbound email data.
Uses regex to parse the recipient's name, title, agency, and jurisdiction
from the To: field, Subject, and email body.
"""
import re
from typing import Optional

# Common LE titles to scan for in subject/body
_LE_TITLES = [
    "Chief of Police", "Police Chief", "Sheriff", "Undersheriff",
    "Deputy Chief", "Assistant Chief", "Lieutenant", "Captain",
    "Commander", "Director", "Superintendent", "Marshal",
    "Commissioner", "Inspector", "Sergeant", "Detective",
]

# Common state abbreviations to help extract jurisdiction
_STATE_ABBREVS = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
    "TX","UT","VT","VA","WA","WV","WI","WY","DC",
}


def _extract_name_from_to(to_field: str) -> str:
    """Extract display name from 'Name <email@domain>' or bare email."""
    if "<" in to_field:
        candidate = to_field.split("<")[0].strip().strip('"').strip("'")
        if candidate:
            return candidate
    # fallback: use local part of email, capitalize
    if "@" in to_field:
        local = to_field.split("@")[0].strip()
        # convert jsmith or j.smith or j_smith to readable
        local = re.sub(r"[._]", " ", local).title()
        return local
    return to_field.strip()


def _extract_title(text: str) -> Optional[str]:
    """Scan text for known LE titles."""
    for title in _LE_TITLES:
        if re.search(re.escape(title), text, re.IGNORECASE):
            return title
    return None


def _extract_agency_from_email(email_addr: str) -> Optional[str]:
    """
    Derive agency name from email domain.
    e.g. jsmith@austinpd.gov -> 'Austin PD'
         chief@houstontx.gov -> 'Houston TX'
         info@sherifforange.org -> 'Sheriff Orange'
    """
    if "@" not in email_addr:
        return None
    domain = email_addr.split("@")[-1].lower()
    # strip TLD
    base = re.sub(r"\.(gov|us|org|net|com)$", "", domain)
    # remove common filler words
    base = re.sub(r"(city|county|dept|department|office|co)\b", "", base)
    base = base.strip("-. ")
    # insert space before known keywords
    base = re.sub(r"(police|sheriff|pd|marshal|constable)", r" \1 ", base, flags=re.IGNORECASE)
    base = re.sub(r"\s+", " ", base).strip().title()
    return base if base else None


def _extract_jurisdiction(email_addr: str, agency: Optional[str]) -> Optional[str]:
    """
    Try to extract city/state from email domain.
    e.g. jsmith@austintx.gov -> 'Austin, TX'
    """
    if "@" not in email_addr:
        return None
    domain = email_addr.split("@")[-1].lower()
    base = re.sub(r"\.(gov|us|org|net|com)$", "", domain)

    # Look for 2-letter state suffix at end of domain base
    match = re.search(r"([a-z]+)(al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy|dc)$", base)
    if match:
        city = match.group(1).title()
        state = match.group(2).upper()
        return f"{city}, {state}"

    return None


def parse_prospect_from_email(email_data: dict) -> Optional[dict]:
    """
    Extract structured prospect info from a raw outbound email dict.
    Returns a dict with: name, first_name, title, agency, jurisdiction
    """
    to_field = email_data.get("to", "")
    subject = email_data.get("subject", "")
    body = email_data.get("body", "")[:2000]

    # Extract bare email address
    email_addr = ""
    if "<" in to_field and ">" in to_field:
        email_addr = to_field.split("<")[1].split(">")[0].strip()
    else:
        email_addr = to_field.strip()

    name = _extract_name_from_to(to_field)
    first_name = name.split()[0] if name else None

    combined_text = f"{to_field} {subject} {body}"
    title = _extract_title(combined_text)
    agency = _extract_agency_from_email(email_addr)
    jurisdiction = _extract_jurisdiction(email_addr, agency)

    return {
        "name": name or None,
        "first_name": first_name or None,
        "title": title,
        "agency": agency,
        "jurisdiction": jurisdiction,
    }
