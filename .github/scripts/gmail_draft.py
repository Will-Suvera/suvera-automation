#!/usr/bin/env python3
"""Create a Gmail DRAFT in a teammate's own mailbox (never sends).

Used by post_call_followup.py so the follow-up email for a meeting lands in the
mailbox of whoever's Fathom account recorded it (Will's calls -> Will's drafts,
Ellena's -> Ellena's). Links stay clean: unlike the claude.ai Gmail connector,
the Gmail API stores exactly what we give it.

Auth: one Google OAuth desktop client shared by the team
  GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET
plus a per-person refresh token minted once by gmail_oauth_setup.py
  GMAIL_REFRESH_TOKEN_WILL / GMAIL_REFRESH_TOKEN_ELLENA / ...
All live in GitHub secrets, so this runs with no laptop and no browser.
"""
import base64
import json
import os
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
SCOPE = "https://www.googleapis.com/auth/gmail.compose"


def _post(url, data, headers=None, form=False):
    body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    h = {"User-Agent": "suvera-automation"}
    h.update(headers or ({"Content-Type": "application/x-www-form-urlencoded"} if form
                         else {"Content-Type": "application/json"}))
    with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=h), timeout=45) as r:
        return json.loads(r.read())


def access_token(account):
    """Fresh access token for this account, or None if it isn't set up yet."""
    rt = os.environ.get("GMAIL_REFRESH_TOKEN_" + account.upper(), "").strip()
    cid = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    cs = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    if not (rt and cid and cs):
        return None
    return _post(TOKEN_URL, {"client_id": cid, "client_secret": cs,
                             "refresh_token": rt, "grant_type": "refresh_token"}, form=True)["access_token"]


def create_draft(account, to, subject, text, html=None, cc=None):
    """Draft in `account`'s mailbox. Returns the draft id, or None if not set up."""
    tok = access_token(account)
    if not tok:
        return None
    msg = MIMEMultipart("alternative") if html else MIMEText(text, "plain", "utf-8")
    if html:
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    msg["To"] = to if isinstance(to, str) else ", ".join(to)
    if cc:
        msg["Cc"] = cc if isinstance(cc, str) else ", ".join(cc)
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return _post(DRAFTS_URL, {"message": {"raw": raw}},
                 {"Authorization": "Bearer " + tok, "Content-Type": "application/json"})["id"]
