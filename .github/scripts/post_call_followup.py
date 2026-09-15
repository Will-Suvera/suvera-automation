#!/usr/bin/env python3
"""Finish a prospect call's follow-up once its Dock workspace is published.

Picks Partner Meeting Library pages (created in the last --hours) that have a
Proposal Doc (made by build_proposal.py) and an empty "Follow-up". When the
Dock builder has uploaded the proposal PDF and published (it writes
"Dock Public URL"), this:
  1. creates a Gmail DRAFT in Will's mailbox (never sent) to Attendee Emails,
     via the Apps Script web app's draft action (clean links - the claude.ai
     Gmail connector rewrites links). Will's own calls only.
  2. posts in the meeting's Slack thread: Dock link, draft status, and the two
     Share-panel clicks Dock's API can't do (add attendees as Collaborators
     without a message; General access -> Restricted Email).
  3. stamps "Follow-up" on the page so it happens once.

Usage: post_call_followup.py [--hours 72] [--wait-minutes 0] [--dry-run] [--test-to addr]
  --wait-minutes N  keep polling every 3 min for pages still waiting on Dock
  --test-to addr    make the draft to this address only; no Slack, no stamp
Env: NOTION_TOKEN, SLACK_BOT_TOKEN, DRIVE_WEBAPP_URL, DRIVE_WEBAPP_SECRET
"""
import html
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

DS = "8115f0ee-00c8-488a-a05b-57726af0acf4"
CHANNEL = "C0APW8DSA4R"
UA = {"User-Agent": "Mozilla/5.0 (suvera-automation)"}


def log(*a):
    print("[followup]", *a, flush=True)


def call(url, body=None, headers=None, method=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={**UA, **(headers or {})}, method=method or ("GET" if body is None else "POST"))
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def notion(path, body=None, method=None):
    return call("https://api.notion.com/v1" + path, body, {
        "Authorization": "Bearer " + os.environ["NOTION_TOKEN"],
        "Notion-Version": "2025-09-03", "Content-Type": "application/json"}, method)


def text(p):
    if not p:
        return ""
    v = p.get(p["type"])
    if isinstance(v, list):
        return "".join(t.get("plain_text", "") for t in v)
    if isinstance(v, dict):
        return v.get("name", "") or v.get("start", "")
    return v or ""


def pending(hours):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {"filter": {"and": [
        {"timestamp": "created_time", "created_time": {"on_or_after": since}},
        {"property": "Proposal Doc", "url": {"is_not_empty": True}},
        {"property": "Follow-up", "rich_text": {"is_empty": True}}]}, "page_size": 50}
    return notion(f"/data_sources/{DS}/query", body).get("results", [])


def webapp_version():
    try:
        return int(call(os.environ["DRIVE_WEBAPP_URL"]).get("version") or 1)
    except Exception as e:
        log("web app health check failed:", e)
        return 0


def to_html(body, link):
    out = []
    for para in body.split("\n\n"):
        p = html.escape(para)
        if "{DOCK_LINK}" in p:
            a = f'<a href="{html.escape(link)}">'
            if " here" in p:
                p = p.replace(": {DOCK_LINK}", "").replace(" {DOCK_LINK}", "").replace("{DOCK_LINK}", "")
                p = p.replace(" here", f" {a}here</a>", 1)
            else:
                p = p.replace("{DOCK_LINK}", f"{a}{html.escape(link)}</a>")
        out.append("<p>" + p.replace("\n", "<br>") + "</p>")
    return "".join(out)


def slack(ts, msg):
    if not (ts and os.environ.get("SLACK_BOT_TOKEN")):
        return
    r = call("https://slack.com/api/chat.postMessage",
             {"channel": CHANNEL, "thread_ts": ts, "text": msg, "unfurl_links": False},
             {"Authorization": "Bearer " + os.environ["SLACK_BOT_TOKEN"], "Content-Type": "application/json; charset=utf-8"})
    log("slack", r.get("ok"), r.get("error", ""))


def handle(page, version, dry, test_to):
    pr = page["properties"]
    practice = text(pr.get("Practice")) or text(pr.get("Meeting"))
    account = (text(pr.get("Fathom Account")) or "will").lower()
    emails = [e.strip() for e in text(pr.get("Attendee Emails")).split(",") if "@" in e]
    link, ts = text(pr.get("Dock Public URL")), text(pr.get("Slack TS"))
    body = text(pr.get("Follow-up Email")) or "Hi all,\n\nI've put everything we covered in one place for you here: {DOCK_LINK}\n\nVery best,\nWill"
    subject = f"Suvera <> {practice}"
    plain = body.replace("{DOCK_LINK}", link)
    note = ""
    if account != "will":
        note = f"no draft ({account}'s call - drafts only go to Will's Gmail)"
    elif not emails and not test_to:
        note = "no draft (no attendee emails)"
    elif version < 2:
        note = "no draft (Apps Script web app not yet redeployed with the draft action)"
    elif dry:
        note = "dry run"
        print(subject, "->", test_to or emails, "\n" + plain, "\n" + to_html(body, link))
    else:
        r = call(os.environ["DRIVE_WEBAPP_URL"], {"secret": os.environ["DRIVE_WEBAPP_SECRET"], "action": "draft",
                                                  "to": test_to or ", ".join(emails), "subject": subject,
                                                  "text": plain, "html": to_html(body, link)})
        note = f"draft {r.get('draft_id')}" if r.get("ok") else f"draft failed: {r}"
    log(practice, "|", note)
    if test_to or dry:
        return
    who = ", ".join(emails) or "the attendees"
    msg = (f":white_check_mark: *Dock published* for {practice}: <{link}|open the workspace>\n"
           + (":envelope: Follow-up email is in Will's Gmail drafts (not sent) - check it, then send.\n"
              if note.startswith("draft ") else f":envelope: Follow-up email: {note}.\n")
           + f"*Two clicks left in Dock (Share):* add {who} as *Collaborators* (untick the invite message), "
             "then set General access to *Restricted Email*.")
    slack(ts, msg)
    stamp = f"done {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}: {note}"
    notion(f"/pages/{page['id']}", {"properties": {"Follow-up": {"rich_text": [{"type": "text", "text": {"content": stamp}}]}}}, "PATCH")


def main(argv):
    arg = lambda f, d=None: argv[argv.index(f) + 1] if f in argv else d
    hours, wait = float(arg("--hours", 72)), float(arg("--wait-minutes", 0))
    dry, test_to = "--dry-run" in argv, arg("--test-to")
    deadline = time.time() + wait * 60
    version = webapp_version()
    log("web app version", version)
    done = set()
    while True:
        pages = [p for p in pending(hours) if p["id"] not in done]
        ready = [p for p in pages if text(p["properties"].get("Dock Public URL"))]
        for p in ready:
            try:
                handle(p, version, dry, test_to)
            except Exception as e:
                log("error on", p["id"], e)
            done.add(p["id"])
        waiting = len(pages) - len(ready)
        log(f"handled {len(ready)}, waiting on Dock: {waiting}")
        if not waiting or time.time() > deadline or dry or test_to:
            break
        time.sleep(180)


if __name__ == "__main__":
    main(sys.argv[1:])
