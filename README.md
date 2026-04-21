# suvera-automation

Automation for Suvera's commercial / product-feedback workflows. Two
workflows:

1. **process-meetings** — every 5 min during UK working hours, fires the
   Claude Code routine that polls Fathom → Notion → Slack with clips.
2. **watchdog** — once daily at 19:30 UTC, reconciles Fathom directly
   against what the routine claims to have processed. Posts a list to
   Slack so Will can eyeball drift.

GitHub Actions is the sole cron. Both claude.ai-side scheduled triggers
have been disabled (they were hitting rate limits).

## What's here

- `.github/workflows/process-meetings.yml` — every 5 min Mon–Fri 07:00–18:59
  UTC. POSTs to `POST /v1/claude_code/routines/{id}/fire` on
  `api.anthropic.com`. The pipeline (poll Fathom → dedupe → Notion page →
  Master Synthesis → Slack main + thread → 5 video clips) lives inside the
  routine's prompt, not this repo.

  API reference: https://code.claude.com/docs/en/routines#add-an-api-trigger

- `.github/workflows/watchdog.yml` — pure bash, no Claude call. Queries
  Fathom Will + Caitlin accounts for the last 24h of external meetings,
  counts "Planner" mentions in each transcript, and posts a reconciliation
  report to Slack `C0APW8DSA4R`. Exists because the 2026-04-17 incident
  showed the main routine can silently no-op (routine fires, Fathom returns
  meetings, Notion creates fail, nobody notices). The watchdog is
  independent of the routine, so if the routine is broken the watchdog
  still reports what *should* have been processed.

## Setup

1. **Add an API trigger to the routine** (one-time):
   - Go to https://claude.ai/code/routines
   - Click the `process-meetings-auto` routine
   - Click the pencil icon (Edit routine)
   - Scroll to **Select a trigger** → **Add another trigger** → **API**
   - Click **Generate token**, copy immediately (shown once only)

2. **GitHub Secrets** — in repo settings → Secrets and variables → Actions:

   For `process-meetings.yml`:
   - `CLAUDE_API_TOKEN` — the `sk-ant-oat01-...` token from step 1.
   - `TRIGGER_ID` — `trig_01XNRjSRFpiybi9bVYXvEYJd`
     (the `process-meetings-auto` routine).

   For `watchdog.yml`:
   - `FATHOM_WILL_KEY` — Will's Fathom API key.
   - `FATHOM_CAITLIN_KEY` — Caitlin's Fathom API key.
   - `SLACK_BOT_TOKEN` — `xoxb-...` bot token with `chat:write` scope
     for channel `C0APW8DSA4R`.

3. **Verify** — Actions tab → pick the workflow → **Run workflow** for a
   one-off run. Inspect logs.

## Why this shape

- **GitHub Actions cron min is 5 minutes** — much better than claude.ai's
  1-hour minimum for scheduled triggers alone.
- **Public repo** — unlimited Actions minutes on free tier. `*/5` = 288 runs/
  day = ~9,000/month, which would burn through the 2,000-min private free
  tier fast.
- **Trigger body is delegated** — all credentials (Fathom, Slack, Notion)
  stay embedded in the trigger prompt on claude.ai. Only the short-lived
  claude.ai API token needs to live in GitHub Secrets.
- **No claude.ai cron** — both claude.ai-side scheduled triggers
  (`trig_01XNRjSRFpiybi9bVYXvEYJd` hourly, and `trig_016CBXjpF48xxLL4zd3FmSnn`
  hourly) have been disabled because they were driving
  subscription rate limits. GitHub Actions is the only thing that fires
  the routine now; the API trigger on the routine stays active.
- **Belt-and-braces moved to the watchdog** — if GH Actions has a cron
  hiccup (they can be delayed 5–15 min under load) the next fire catches
  it; if the routine itself silently breaks, the daily watchdog surfaces
  it.

## Future

If 5-min latency isn't enough and we want true real-time per-meeting
triggering, add a tiny webhook relay (Val.town / Deno Deploy / Cloudflare
Worker) that receives Fathom webhooks and calls the `repository_dispatch`
API to fire this workflow. Swap the `on:` block from `schedule:` to
`repository_dispatch:` when ready. Scaffolding for the Cloudflare Worker
path already exists at
`Platform <> Commercial Sync/automation/fathom-webhook/`.
