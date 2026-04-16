# suvera-automation

Automation for Suvera's commercial / product-feedback workflows. Currently one
workflow lives here: firing the `/process-meetings` pipeline every 5 minutes so
new Fathom partner meetings land in Notion + Slack within minutes of ending.

## What's here

- `.github/workflows/process-meetings.yml` — runs every 5 min (GitHub Actions
  cron minimum) and POSTs to the Claude Code
  `POST /v1/claude_code/routines/{id}/fire` endpoint on `api.anthropic.com`.
  The actual pipeline (poll Fathom → dedupe → Notion page → Master Synthesis
  → Slack main + thread → 5 video clips) lives inside the routine's prompt,
  not this repo. That keeps the workflow minimal.

  API reference: https://code.claude.com/docs/en/routines#add-an-api-trigger

## Setup

1. **Add an API trigger to the routine**:
   - Go to https://claude.ai/code/routines
   - Click the `process-meetings-auto` routine
   - Click the pencil icon (Edit routine)
   - Scroll to **Select a trigger** → **Add another trigger** → **API**
   - Click **Generate token**, copy immediately (shown once only)

2. **Secrets** — in GitHub repo settings → Secrets and variables → Actions:
   - `CLAUDE_API_TOKEN` — the `sk-ant-oat01-...` token from step 1.
   - `TRIGGER_ID` — the routine ID. Current value:
     `trig_01XNRjSRFpiybi9bVYXvEYJd` (the `process-meetings-auto` routine).
     Routine IDs use the `trig_` prefix — the path parameter in the `/fire`
     URL is the same ID you see in the CLI / `RemoteTrigger.list`.

2. **Verify** — after pushing, go to the Actions tab → "Process Fathom
   meetings" → **Run workflow** to fire a one-off run. Inspect the logs.

## Why this shape

- **GitHub Actions cron min is 5 minutes** — much better than claude.ai's
  1-hour minimum for scheduled triggers alone.
- **Public repo** — unlimited Actions minutes on free tier. `*/5` = 288 runs/
  day = ~9,000/month, which would burn through the 2,000-min private free
  tier fast.
- **Trigger body is delegated** — all credentials (Fathom, Slack, Notion)
  stay embedded in the trigger prompt on claude.ai. Only the short-lived
  claude.ai API token needs to live in GitHub Secrets.
- **Belt and braces** — the hourly scheduled trigger on claude.ai itself
  also stays enabled, so if GitHub Actions has a cron hiccup (they can be
  delayed 5–15 min under load), the hourly poll still catches everything
  within an hour.

## Future

If 5-min latency isn't enough and we want true real-time per-meeting
triggering, add a tiny webhook relay (Val.town / Deno Deploy / Cloudflare
Worker) that receives Fathom webhooks and calls the `repository_dispatch`
API to fire this workflow. Swap the `on:` block from `schedule:` to
`repository_dispatch:` when ready. Scaffolding for the Cloudflare Worker
path already exists at
`Platform <> Commercial Sync/automation/fathom-webhook/`.
