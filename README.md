# suvera-automation

Automation for Suvera's commercial / product-feedback workflows. Two
workflows, both 100% free and subscription-funded:

1. **process-meeting-webhook** — fires per-meeting when the Fathom webhook
   relay (Cloudflare Worker) calls `repository_dispatch`. Runs Claude Code
   via `anthropics/claude-code-action@v1` under `CLAUDE_CODE_OAUTH_TOKEN`
   (Max subscription, no API billing). Produces the full pipeline: analysis →
   Notion page → Master Synthesis update → Slack main + thread → 5 video
   clips via ffmpeg.
2. **watchdog** — once daily at 19:30 UTC, pure bash. Queries Fathom
   directly, counts Planner mentions per transcript, posts a reconciliation
   report to Slack so silent webhook-delivery failures surface within 24h.

## What's here

- `.github/workflows/process-meeting-webhook.yml` — triggered by
  `repository_dispatch: [fathom_meeting_ended]`. The Cloudflare Worker at
  `../fathom-webhook/` is the only thing that fires these dispatches,
  after verifying a Svix signature from Fathom.
- `.github/workflows/watchdog.yml` — daily 19:30 UTC. Queries Fathom
  Will + Caitlin accounts for the last 24h of external meetings, counts
  "Planner" mentions in each transcript, and posts a reconciliation
  report to Slack `C0APW8DSA4R`.

## Architecture (full path)

```
Fathom meeting ends
  └── Fathom webhook (Svix-signed POST)
      └── Cloudflare Worker (../fathom-webhook/)
          ├── verify Svix signature → identify account
          └── POST /repos/Will-Suvera/suvera-automation/dispatches
              └── process-meeting-webhook.yml fires
                  └── anthropics/claude-code-action@v1 w/ CLAUDE_CODE_OAUTH_TOKEN
                      └── full pipeline → Notion, Slack, ffmpeg clips
```

Daily 19:30 UTC, independent of the webhook path:

```
watchdog.yml cron
  └── curl Fathom Will+Caitlin (last 24h)
  └── count "planner" in each transcript
  └── POST Slack reconciliation list
```

## GitHub Secrets required

| Secret | Used by | How to get |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | webhook workflow | `claude setup-token` on your Mac |
| `NOTION_TOKEN` | webhook workflow | Notion internal integration (`ntn_…`) |
| `FATHOM_WILL_KEY` | watchdog + webhook workflow | Fathom → Settings → API |
| `FATHOM_CAITLIN_KEY` | watchdog + webhook workflow | Fathom → Settings → API |
| `SLACK_BOT_TOKEN` | watchdog + webhook workflow | Slack app with `chat:write`, `files:write` |

See `../fathom-webhook/SETUP.md` for the one-time setup runbook.

## Why this shape

- **Zero API billing** — `CLAUDE_CODE_OAUTH_TOKEN` counts against your Max
  subscription quota, not pay-per-use API credits. Earlier polling
  architecture fired `api.anthropic.com/v1/claude_code/routines/{id}/fire`
  which was API-billed and hit the spend cap.
- **No polling** — webhook fires exactly once per meeting, seconds after
  Fathom finishes processing. No wasted quota on empty polls.
- **Public repo** — unlimited GitHub Actions minutes on free tier.
- **Belt-and-braces** — the watchdog catches anything the webhook path
  missed (delivery failure, workflow crash, silent no-op) within 24h.
- **No claude.ai cron** — both prior claude.ai scheduled triggers
  (`trig_01XNRjSRFpiybi9bVYXvEYJd`, `trig_016CBXjpF48xxLL4zd3FmSnn`) were
  disabled because they were driving subscription rate limits. Kept
  cold-stored on claude.ai as a historical reference.

## Future

If latency ever needs to be <10s end-to-end, the next optimization would
be to drop the ffmpeg clip step from the critical path and run it
asynchronously as a separate dispatched workflow. Current latency is
~5–10 min (dominated by full-format analysis + 5 × ffmpeg transcodes).
