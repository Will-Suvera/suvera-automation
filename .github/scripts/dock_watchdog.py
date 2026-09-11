#!/usr/bin/env python3
"""Alert once in a meeting's Slack thread when its Dock workspace hasn't been built.

Run by dock-watchdog.yml: 90 minutes after each "Process meeting (webhook)" run
completes (event-driven, no scheduler), plus any manual / scheduled sweep.
Looks at Partner Meeting Library pages from the last 72 hours that have a Slack
card but no Dock Workspace. Alerts when a page is older than --min-age minutes
or the builder marked it failed, then stamps "watchdog alerted" so it never
alerts twice.

Usage: dock_watchdog.py [--min-age 90] [--dry-run]
Env:   NOTION_TOKEN, SLACK_BOT_TOKEN
"""
import datetime as dt
import json
import os
import sys
import urllib.request

DS = "8115f0ee-00c8-488a-a05b-57726af0acf4"   # Partner Meeting Library
CHANNEL = "C0APW8DSA4R"


def call(url, body=None, headers=None, method=None):
    r = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                               headers=headers or {}, method=method or ("GET" if body is None else "POST"))
    with urllib.request.urlopen(r, timeout=30) as x:
        return json.loads(x.read())


def text(p):
    if not p:
        return ""
    v = p.get(p["type"])
    return "".join(t.get("plain_text", "") for t in v) if isinstance(v, list) else (v or "")


def main():
    argv = sys.argv
    min_age = int(argv[argv.index("--min-age") + 1]) if "--min-age" in argv else 90
    dry = "--dry-run" in argv
    N = {"Authorization": "Bearer " + os.environ["NOTION_TOKEN"],
         "Notion-Version": "2025-09-03", "Content-Type": "application/json"}
    now = dt.datetime.now(dt.timezone.utc)
    q = call(f"https://api.notion.com/v1/data_sources/{DS}/query", {
        "page_size": 50,
        "filter": {"and": [
            {"property": "Slack TS", "rich_text": {"is_not_empty": True}},
            {"property": "Dock Workspace", "url": {"is_empty": True}},
            {"timestamp": "created_time", "created_time": {"after": (now - dt.timedelta(hours=72)).isoformat()}}]}}, N)
    alerted = 0
    for pg in q["results"]:
        pr = pg["properties"]
        status = text(pr.get("Dock Status"))
        age = (now - dt.datetime.fromisoformat(pg["created_time"].replace("Z", "+00:00"))).total_seconds() / 60
        practice = text(pr.get("Practice")) or text(pr.get("Meeting"))
        if "watchdog alerted" in status or not (age > min_age or status.startswith("failed")):
            print(f"ok for now: {practice} ({int(age)} min, status '{status or '-'}')")
            continue
        reason = status if status.startswith("failed") else f"no workspace after {int(age)} minutes"
        msg = (f":warning: The Dock workspace for *{practice}* hasn't been built automatically "
               f"({reason}). Will, this one needs a look.")
        if dry:
            print(f"DRY RUN would alert: {practice} - {reason}")
            continue
        res = call("https://slack.com/api/chat.postMessage",
                   {"channel": CHANNEL, "thread_ts": text(pr.get("Slack TS")), "text": msg},
                   {"Authorization": "Bearer " + os.environ["SLACK_BOT_TOKEN"],
                    "Content-Type": "application/json; charset=utf-8"})
        print(practice, "| slack ok" if res.get("ok") else f"| slack error {res.get('error')}")
        stamp = (status + " | " if status else "") + "watchdog alerted " + now.strftime("%Y-%m-%dT%H:%MZ")
        call(f"https://api.notion.com/v1/pages/{pg['id']}",
             {"properties": {"Dock Status": {"rich_text": [{"type": "text", "text": {"content": stamp[:1900]}}]}}},
             N, "PATCH")
        alerted += 1
    print(f"{len(q['results'])} meeting(s) awaiting a workspace, {alerted} newly alerted")


if __name__ == "__main__":
    main()
