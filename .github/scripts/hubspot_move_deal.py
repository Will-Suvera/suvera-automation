#!/usr/bin/env python3
"""Move a processed partner meeting's HubSpot Planner deal forward.

After the meeting pipeline has written up a meeting in Notion, find the
practice's deal in the "Primary Care Tech Growth" pipeline (3277290730) by ODS
code and move it Signed-up List / Demo Booked -> Demo Held -> Proposal Sent.
Two separate moves so HubSpot records both stage-entry dates (the funnel
dashboard measures stage timings from hs_v2_date_entered_<stage>).

Never moves a deal backwards: a deal already at Proposal Sent or later
(Docusign Sent, DPA Signed, Live, Dropped Out) is left alone. Posts one line in
the meeting's Slack thread when it moves a deal or can't find one.

Usage: hubspot_move_deal.py --rid <Fathom recording id> [--dry-run] [--no-slack]
Env:   NOTION_TOKEN, HUBSPOT_TOKEN, SLACK_BOT_TOKEN (optional)
"""
import json
import os
import sys
import urllib.request

DS = "8115f0ee-00c8-488a-a05b-57726af0acf4"          # Partner Meeting Library
PIPELINE = "3277290730"                              # Primary Care Tech Growth
SIGNED_UP, DEMO_BOOKED, DEMO_HELD, PROPOSAL = "4489053409", "5147362520", "5017986288", "4489053410"
EARLY = (SIGNED_UP, DEMO_BOOKED, DEMO_HELD)
LABEL = {SIGNED_UP: "Signed-up List", DEMO_BOOKED: "Demo Booked", DEMO_HELD: "Demo Held",
         PROPOSAL: "Proposal Sent", "5898844361": "Docusign Sent", "4489053411": "DPA Signed Onboard Ready",
         "4487571659": "Full Functionality Live", "4527836370": "Dropped Out"}
HS = "https://api-eu1.hubapi.com"
PORTAL = "143576889"
CHANNEL = "C0APW8DSA4R"


def call(url, body=None, headers=None, method=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers=headers or {}, method=method or ("GET" if body is None else "POST"))
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def notion(path, body=None, method=None):
    return call("https://api.notion.com/v1" + path, body, {
        "Authorization": "Bearer " + os.environ["NOTION_TOKEN"],
        "Notion-Version": "2025-09-03", "Content-Type": "application/json"}, method)


def hs(path, body=None, method=None):
    return call(HS + path, body, {"Authorization": "Bearer " + os.environ["HUBSPOT_TOKEN"],
                                  "Content-Type": "application/json"}, method)


def text(p):
    if not p:
        return ""
    v = p.get(p["type"])
    return "".join(t.get("plain_text", "") for t in v) if isinstance(v, list) else (v or "")


def slack(thread_ts, msg, enabled):
    if not (enabled and thread_ts and os.environ.get("SLACK_BOT_TOKEN")):
        return
    call("https://slack.com/api/chat.postMessage", {"channel": CHANNEL, "thread_ts": thread_ts, "text": msg},
         {"Authorization": "Bearer " + os.environ["SLACK_BOT_TOKEN"],
          "Content-Type": "application/json; charset=utf-8"})


def deals_for_codes(codes):
    """Planner-pipeline deals on companies whose ODS matches any of the codes."""
    comps = hs("/crm/v3/objects/companies/search", {
        "filterGroups": [{"filters": [{"propertyName": p, "operator": "IN", "values": codes}]}
                         for p in ("ods_unique", "practice_code")],
        "properties": ["name"], "limit": 20}).get("results", [])
    ids = []
    for c in comps:
        for t in hs(f"/crm/v4/objects/companies/{c['id']}/associations/deals").get("results", []):
            ids.append(str(t["toObjectId"]))
    if not ids:
        return comps, []
    got = hs("/crm/v3/objects/deals/batch/read", {
        "properties": ["dealname", "pipeline", "dealstage", "hs_lastmodifieddate"],
        "inputs": [{"id": x} for x in dict.fromkeys(ids)]}).get("results", [])
    return comps, [d for d in got if d["properties"].get("pipeline") == PIPELINE]


def main():
    argv = sys.argv
    rid = argv[argv.index("--rid") + 1] if "--rid" in argv else os.environ.get("RID", "")
    dry, use_slack = "--dry-run" in argv, "--no-slack" not in argv and "--dry-run" not in argv
    if not rid:
        sys.exit("no recording id")
    q = notion(f"/data_sources/{DS}/query", {"page_size": 1,
               "filter": {"property": "Meeting ID", "rich_text": {"equals": str(rid)}}})
    if not q.get("results"):
        print(f"{rid}: no Notion page (the pipeline didn't write this meeting up) - nothing to do")
        return
    page = q["results"][0]
    pr = page["properties"]
    practice = text(pr.get("Practice")) or text(pr.get("Meeting"))
    ods, pcn_ods = text(pr.get("ODS Code")).strip().upper(), text(pr.get("PCN ODS Code")).strip().upper()
    ts = text(pr.get("Slack TS")).strip()
    if not (ods or pcn_ods):
        print(f"{practice}: no ODS code on the meeting page - can't match a HubSpot deal safely")
        slack(ts, f":grey_question: HubSpot: couldn't match *{practice}* to a deal (no ODS code on the meeting page).", use_slack)
        return
    comps, deals = deals_for_codes([ods]) if ods else ([], [])
    if not deals and pcn_ods:  # PCN-level deals sit on the PCN's company
        comps, deals = deals_for_codes([pcn_ods])
    if not deals:
        tried = " or ".join(c for c in (ods, pcn_ods) if c)
        print(f"{practice}: no Primary Care Tech Growth deal on the practice or PCN ({tried})")
        slack(ts, f":grey_question: HubSpot: no Primary Care Tech Growth deal found for *{practice}* ({tried}). Add one so this meeting is tracked.", use_slack)
        return
    early = [d for d in deals if d["properties"]["dealstage"] in EARLY]
    if not early:
        stages = ", ".join(f"{d['properties']['dealname']} at {LABEL.get(d['properties']['dealstage'], d['properties']['dealstage'])}" for d in deals)
        print(f"{practice}: already at or beyond Proposal Sent ({stages}) - left alone")
        return
    deal = max(early, key=lambda d: d["properties"].get("hs_lastmodifieddate") or "")
    stage = deal["properties"]["dealstage"]
    raw = (deal["properties"].get("dealname") or "").strip()
    name = raw if raw and not raw.startswith("-") else f"{practice} deal"  # some deals have no practice name
    steps = [PROPOSAL] if stage == DEMO_HELD else [DEMO_HELD, PROPOSAL]
    url = f"https://app-eu1.hubspot.com/contacts/{PORTAL}/record/0-3/{deal['id']}"
    print(f"{practice}: deal {deal['id']} '{name}' {LABEL[stage]} -> " + " -> ".join(LABEL[s] for s in steps) + (" (dry run)" if dry else ""))
    if dry:
        return
    for s in steps:
        hs(f"/crm/v3/objects/deals/{deal['id']}", {"properties": {"dealstage": s}}, "PATCH")
    rec = pr.get("HubSpot Record") or {}
    if rec.get("type") == "url" and not rec.get("url"):
        notion(f"/pages/{page['id']}", {"properties": {"HubSpot Record": {"url": url}}}, "PATCH")
    elif rec.get("type") == "rich_text" and not text(rec):
        notion(f"/pages/{page['id']}", {"properties": {"HubSpot Record": {"rich_text": [{"type": "text", "text": {"content": url}}]}}}, "PATCH")
    slack(ts, f":briefcase: HubSpot: moved <{url}|{name}> to *Proposal Sent* (via Demo Held) now the meeting is done.", use_slack)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never fail the meeting pipeline over HubSpot
        print(f"::warning::HubSpot deal move failed: {str(e)[:300]}")
