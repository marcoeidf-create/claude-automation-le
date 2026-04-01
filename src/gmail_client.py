"""
Gmail API client.

Handles OAuth2 authentication, reading the sent folder to find unanswered
threads, checking for replies on tracked prospects, saving drafts, and
sending scheduled drafts when their time arrives.
"""

import base64
import os
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# readonly  — read sent folder and threads
# compose   — create drafts AND send messages/drafts
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


def get_gmail_service():
    """
    Authenticate via OAuth2 and return an authorized Gmail service object.

    On first run this opens a browser window for user authorization and saves
    token.json for future runs. Subsequent runs reuse the saved token,
    refreshing automatically when expired. Prints confirmation after auth so
    the user knows the scan is starting without a second command.
    """
    credentials_file = os.environ.get("GMAIL_CREDENTIALS_FILE", "credentials.json")
    token_file = "token.json"
    creds = None
    was_fresh_auth = False

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_file):
                raise FileNotFoundError(
                    f"Gmail credentials file not found: {credentials_file}\n"
                    "Download it from Google Cloud Console → APIs & Services → Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_file, SCOPES,
                redirect_uri="urn:ietf:wg:oauth:2.0:oob",
            )
            # Headless/codespace flow: print the URL, user opens it in any browser,
            # pastes the authorization code back into the terminal.
            auth_url, _ = flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
                prompt="consent",
            )
            print("\n" + "=" * 62)
            print("  GMAIL AUTHORIZATION REQUIRED")
            print("=" * 62)
            print("\n  Open this URL in your browser:\n")
            print(f"  {auth_url}\n")
            print("  After approving, Google will show you an authorization code.")
            print("  Paste it here and press Enter:\n")
            auth_code = input("  Authorization code: ").strip()
            flow.fetch_token(code=auth_code)
            creds = flow.credentials
            was_fresh_auth = True

        with open(token_file, "w") as f:
            f.write(creds.to_json())

        if was_fresh_auth:
            print("  Authorization complete. token.json saved.")
            print("  Starting sent folder scan now...")

    return build("gmail", "v1", credentials=creds)


def _extract_body(payload: dict) -> str:
    """
    Recursively walk a Gmail message payload and return the plain-text body.
    Handles simple messages, multipart/alternative, and multipart/mixed.
    """
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    if "parts" in payload:
        for part in payload["parts"]:
            body = _extract_body(part)
            if body:
                return body

    return ""


def _get_header(headers: list, name: str) -> str:
    """Return the value of a named email header (case-insensitive)."""
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse an RFC 2822 date string into an aware datetime, or return None."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def check_for_replies(service, prospects: list) -> list:
    """
    Check all tracked prospects with thread_ids for incoming replies.

    Returns a list of prospect dicts that now have at least one incoming
    message — meaning the recipient replied since we first tracked them.
    Does not modify the tracker; caller is responsible for updating status.

    Skips prospects already marked as replied or meeting_booked.
    """
    newly_replied = []
    skip_statuses = {"replied", "meeting_booked", "cancelled"}

    for prospect in prospects:
        thread_id = prospect.get("thread_id")
        if not thread_id or prospect.get("status") in skip_statuses:
            continue

        try:
            thread = service.users().threads().get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=["From"],
            ).execute()

            for msg in thread.get("messages", []):
                labels = msg.get("labelIds", [])
                # INBOX label means the message was received (not sent by us)
                if "INBOX" in labels:
                    newly_replied.append(prospect)
                    break

        except HttpError as e:
            status_code = e.resp.status if hasattr(e, "resp") else None
            if status_code == 404:
                continue  # Thread was deleted — not an error
            print(f"  Warning: error checking thread {thread_id} — {e}")

    return newly_replied


def get_unanswered_sent_emails(service, days_threshold: int = 7) -> list:
    """
    Return sent email threads that have received no reply for more than
    `days_threshold` days.

    For each qualifying thread returns a dict with:
        thread_id, message_id, to, subject, body, sent_date, days_since_sent
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)

    sent_messages = []
    page_token = None
    print(f"  Scanning sent folder (threshold: {days_threshold} days)...")

    while True:
        try:
            resp = service.users().messages().list(
                userId="me",
                labelIds=["SENT"],
                pageToken=page_token,
                maxResults=500,
            ).execute()
        except HttpError as e:
            print(f"  Warning: error listing sent messages — {e}")
            break

        sent_messages.extend(resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    thread_ids = {m["threadId"] for m in sent_messages}
    print(f"  Found {len(thread_ids)} sent threads to evaluate")

    unanswered = []

    for thread_id in thread_ids:
        try:
            thread = service.users().threads().get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()

            messages = thread.get("messages", [])
            has_reply = False
            last_sent_msg = None
            last_sent_date = None

            for msg in messages:
                labels = msg.get("labelIds", [])
                headers = msg.get("payload", {}).get("headers", [])
                date_str = _get_header(headers, "Date")
                msg_date = _parse_date(date_str)

                if "SENT" in labels:
                    if last_sent_date is None or (msg_date and msg_date > last_sent_date):
                        last_sent_date = msg_date
                        last_sent_msg = msg
                elif "DRAFT" not in labels:
                    has_reply = True
                    break

            if not has_reply and last_sent_msg and last_sent_date and last_sent_date < cutoff:
                full_msg = service.users().messages().get(
                    userId="me",
                    id=last_sent_msg["id"],
                    format="full",
                ).execute()

                headers = full_msg.get("payload", {}).get("headers", [])
                to_addr = _get_header(headers, "To")
                subject = _get_header(headers, "Subject")
                body = _extract_body(full_msg.get("payload", {}))
                days_silent = (datetime.now(timezone.utc) - last_sent_date).days

                unanswered.append({
                    "thread_id": thread_id,
                    "message_id": last_sent_msg["id"],
                    "to": to_addr,
                    "subject": subject,
                    "body": body,
                    "sent_date": last_sent_date.isoformat(),
                    "days_since_sent": days_silent,
                })

        except HttpError as e:
            print(f"  Warning: error processing thread {thread_id} — {e}")
            continue

    return unanswered


def save_draft(service, to_email: str, subject: str, body: str) -> Optional[str]:
    """
    Save a composed email as a Gmail Draft.
    Returns the draft ID on success, or None on failure.
    """
    try:
        raw_message = (
            f"To: {to_email}\r\n"
            f"Subject: {subject}\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n"
            f"\r\n"
            f"{body}"
        )
        encoded = base64.urlsafe_b64encode(raw_message.encode("utf-8")).decode("utf-8")
        draft = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": encoded}},
        ).execute()
        return draft["id"]
    except HttpError as e:
        print(f"  Warning: failed to save draft for {to_email} — {e}")
        return None


def send_draft(service, draft_id: str) -> bool:
    """
    Send an existing Gmail Draft by its ID.

    Returns True on success. Returns False if the draft no longer exists
    (user deleted it to cancel the send). Raises on other errors.
    """
    try:
        service.users().drafts().send(
            userId="me",
            body={"id": draft_id},
        ).execute()
        return True
    except HttpError as e:
        status_code = e.resp.status if hasattr(e, "resp") else None
        if status_code == 404:
            return False  # Draft was deleted — treat as user-cancelled
        raise
