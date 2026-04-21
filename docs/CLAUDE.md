# Suvera Partner-Meeting Automation

Full documentation for the hands-free pipeline that turns Fathom partner meetings into Notion analyses + Slack posts + video clips. Everything runs on the Max subscription — **zero API billing**.

> **🚨 Current production blocker (Apr 22 2026):** the Cloudflare Worker's `GITHUB_PAT` needs **Contents: Read AND write** (currently just Read → `POST /dispatches` returns 403). Until that's fixed, Fathom meetings will NOT auto-process. Fix at https://github.com/settings/personal-access-tokens → edit the suvera-automation token → Contents: Read and write. Then `gh workflow run test-webhook.yml` to re-verify.

---

## 1. What this automates

When a Fathom recording finishes on Will's or Caitlin's account:

1. Fathom fires a signed webhook
2. A Cloudflare Worker verifies the Svix signature and triggers a GitHub Actions workflow
3. The workflow runs Claude Code (subscription-funded) which:
   - Fetches the transcript
   - Filters: external invitees only + "Planner" mentioned ≥3 times
   - Writes a full-format analysis to a new Notion page in the Partner Meeting Library
   - Updates the Master Synthesis page
   - Posts a header card to Slack `#partner-meetings`
   - Posts a threaded reply with 10 key quotes
   - Cuts and uploads ~5–10 video clips to the same thread

Two scheduled workflows complement it:

- **Watchdog** (19:30 UTC Mon–Fri) — reconciles Fathom directly against what landed. Catches silent failures.
- **Daily summary** (16:00 UTC daily = 17:00 BST) — Slack digest ranking today's feature requests + gaps by how often they've been cited in prior meetings. Features-only, no problems section. Silent when no meetings that day.

---

## 2. Architecture

```
                   Fathom records a meeting ▶ webhook fires
                                │
                       HTTPS POST (Svix signed)
                                │
                                ▼
         ┌────────────────────────────────────────────┐
         │  Cloudflare Worker                          │
         │    fathom-webhook.<subdomain>.workers.dev   │
         │    • verifies webhook-id/timestamp/sig      │
         │    • identifies account from whsec          │
         │    • POSTs GitHub repository_dispatch       │
         └────────────────────────────────────────────┘
                                │
                                ▼
         ┌────────────────────────────────────────────┐
         │  GitHub Actions                             │
         │    repo: Will-Suvera/suvera-automation      │
         │    workflow: process-meeting-webhook.yml    │
         │    event: repository_dispatch               │
         │    runner: ubuntu-latest, timeout 35m       │
         │    action: anthropics/claude-code-action@v1 │
         │    auth: CLAUDE_CODE_OAUTH_TOKEN (Max sub)  │
         └────────────────────────────────────────────┘
                                │
                                ▼
         ┌────────────────────────────────────────────┐
         │  Claude Code pipeline (subscription runs)   │
         │    1 fetch transcript from Fathom           │
         │    2 filter: external + Planner ≥ 3         │
         │    3 full analysis (no TLDR)                │
         │    4 Notion REST: create page               │
         │    5 Notion REST: patch Master Synthesis    │
         │    6 Slack chat.postMessage (main card)     │
         │    7 Slack chat.postMessage (thread, quotes)│
         │    8 ffmpeg 5–10 clips → Slack 3-step upload│
         └────────────────────────────────────────────┘
```

Parallel observability:

```
  .github/workflows/watchdog.yml      .github/workflows/daily-summary.yml
  cron: 30 19 * * 1-5 (19:30 UTC)     cron: 30 18 * * 1-5 (18:30 UTC)
        │                                     │
  pure-bash reconciliation                Claude Code digest
  (queries Fathom + counts Planner      (reads today's Notion, cross-
   mentions, posts to Slack)             refs themes across library)
```

---

## 3. Repository / directory layout

Two directories under `Platform <> Commercial Sync/automation/`:

### `suvera-automation/` — the GitHub repo (`Will-Suvera/suvera-automation`, public)

```
.github/workflows/
  process-meeting-webhook.yml  ← per-meeting pipeline, triggered by
                                  Cloudflare Worker via repository_dispatch.
                                  Also supports workflow_dispatch for manual
                                  replay (all fields required as inputs).
  watchdog.yml                 ← daily reconciliation (bash only, no Claude).
  daily-summary.yml            ← weekday digest post (Claude Code).
  test-webhook.yml             ← hands-free smoke test of the chain.
README.md
```

### `fathom-webhook/` — Cloudflare Worker source (local, not a git repo)

```
src/worker.ts         ← Svix verification + GitHub repository_dispatch forwarder
wrangler.toml         ← account_id + non-secret vars (GITHUB_OWNER, GITHUB_REPO)
scripts/
  register-webhook.mjs  ← registers the worker URL as a Fathom webhook endpoint
                           and returns the whsec_ (used once per account)
SETUP.md              ← runbook for first-time deploy
README.md             ← architecture + day-to-day ops
package.json          ← wrangler + types
```

---

## 4. Secrets inventory

| Secret | Where it lives | What it's for |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | GitHub repo Secrets | `claude setup-token` output. Auths claude-code-action against Max subscription. **Not API billed.** |
| `NOTION_TOKEN` | GitHub repo Secrets | Notion internal integration (`ntn_…`). Must have Read/Update/Insert on Partner Meeting Library **data_source** `8115f0ee-…` and Master Synthesis page `33135d37-…`. |
| `FATHOM_WILL_KEY` | GitHub repo Secrets | Will's Fathom API key. Used by workflow + watchdog to fetch transcripts. |
| `FATHOM_CAITLIN_KEY` | GitHub repo Secrets | Caitlin's Fathom API key. Same purpose. |
| `SLACK_BOT_TOKEN` | GitHub repo Secrets | `xoxb-…` bot token (Partner-insights-bot). Scopes: `chat:write`, `files:write`. **Missing** `files:read`, `channels:history` — affects surgical clip management. |
| `FATHOM_WEBHOOK_SECRET_WILL` | GitHub repo Secrets **and** Cloudflare | `whsec_…`. GitHub copy used by the smoke test to sign test requests. Cloudflare copy used by the Worker to verify real requests. Must be identical. |
| `GITHUB_PAT` | Cloudflare Worker (only) | Fine-grained PAT on `suvera-automation`. Permission: **Contents: Read and write** (required for `POST /dispatches`). |

Lookup/rotate commands:

```bash
# Check GitHub secrets
cd "$HOME/Platform <> Commercial Sync/automation/suvera-automation"
gh secret list

# Rotate a GitHub secret
gh secret set SECRET_NAME --body "new_value"

# Rotate a Cloudflare Worker secret
cd "$HOME/Platform <> Commercial Sync/automation/fathom-webhook"
echo "new_value" | npx wrangler secret put SECRET_NAME

# Regenerate subscription OAuth token (1-year lifespan)
claude setup-token   # prints new sk-ant-oat01-... → put in CLAUDE_CODE_OAUTH_TOKEN
```

---

## 5. Workflow: process-meeting-webhook.yml

**Triggers:**
- `repository_dispatch` with `event_type: fathom_meeting_ended` (production path, fired by Worker)
- `workflow_dispatch` with fields `{account, recording_id, title, share_url, scheduled_start_time, calendar_invitees_domains_type}` (manual replay)

**Client payload fields** (must all be present):
- `account` — "will" or "caitlin"
- `recording_id` — integer
- `title` — string
- `share_url` — FULL URL e.g. `https://fathom.video/share/SLUG` (not just the slug)
- `scheduled_start_time` — ISO8601
- `calendar_invitees_domains_type` — "one_or_more_external" or "all_internal" (filter exits if not external)

**Max-turns:** 80 (was 40; raised so Step 7 clip uploads fit in budget).
**Timeout:** 35 minutes (was 20; raised after Chipping Norton ran out of time during clip upload).

**Clip selection criteria (Step 7):** strict priority order:
1. Very high explicit praise / buy signal (no lukewarm politeness)
2. Direct feature requests (not meta "are you going to cover X?")
3. Detailed multi-sentence problem explanations (not one-liners)

Quantity flexible 3–10; don't pad to hit a count. At least 1 tier-3 for context.

---

## 6. Workflow: watchdog.yml

Pure bash. Queries Fathom Will + Caitlin directly for last-24h external meetings, counts Planner mentions per transcript, posts a reconciliation list to Slack. Independent of the webhook pipeline — so if the main workflow is silently broken, the watchdog still reports what *should* have been processed.

**What it answers:** "Did today's qualifying meetings actually land in Slack?"

**When to check:** if the daily 19:30 UTC post in `#partner-meetings` shows meetings you don't remember seeing main-posts for, the main pipeline silently dropped them.

---

## 7. Workflow: daily-summary.yml

Claude Code under subscription. **16:00 UTC daily (17:00 BST)**, every day including weekends.

Reads today's new Notion pages, extracts ONLY feature requests + gaps (drops Live + In-build), cross-references each against the full Partner Meeting Library for frequency counts, ranks them most-cited-first, posts to Slack.

**Format:**
```
📊 Partner-call feature digest — {date}
Calls today: N

Feature requests & gaps (most cited → least):
• *<feature in partner's framing>*
  cited N× previously   [links to prior pages]
  _today by: Practice name_
• …
```

Silent if 0 meetings today. No problem section — problems are covered in the per-meeting thread.

---

## 8. Workflow: test-webhook.yml

Hands-free smoke test of the Fathom → Worker → GitHub chain.

**Run:** `gh workflow run test-webhook.yml` (or Actions UI → Run workflow).

**Checks (all must pass):**
1. Worker `GET /` returns 200 with expected JSON
2. Unsigned POST → 400
3. Svix-signed POST with real `whsec_` → 200 with matched account
4. GitHub dispatch fires a new `process-meeting-webhook.yml` run within 30s
5. That run bails fast at the external-meeting filter (because the synthetic payload is flagged `all_internal`) so no Notion/Slack pollution

**Proves:** "Will a real Fathom webhook fire this pipeline unattended?" — yes iff all 5 pass.

---

## 9. Runbook — common tasks

### 9.1 Manually replay a meeting
```bash
cd "$HOME/Platform <> Commercial Sync/automation/suvera-automation"
gh workflow run process-meeting-webhook.yml \
  -f account=will \
  -f recording_id=<RID> \
  -f title="<TITLE>" \
  -f share_url="https://fathom.video/share/<SLUG>" \
  -f scheduled_start_time="2026-04-21T15:00:00Z" \
  -f calendar_invitees_domains_type=one_or_more_external
```

Before firing: check Notion for existing page with that Meeting ID and archive it first if you want to avoid duplicates (webhook path has no dedupe).

### 9.2 Surgical clip edits on an existing thread
If a meeting's auto-uploaded clips don't match the strict criteria, re-curate from a local Mac with ffmpeg + the bot token. Pattern used for Monis Alam / Chipping Norton / Ed Turnham:

1. Get the Slack thread permalink (hover message → ⋯ → Copy link).
2. Extract `thread_ts` from the URL: `p1776808412842459` → `1776808412.842459` (split 6 chars from the right, insert `.`).
3. Fetch transcript:
   ```bash
   curl -sS -H "X-Api-Key: $FATHOM_KEY" "https://api.fathom.ai/external/v1/recordings/$RID/transcript" > /tmp/tx.json
   ```
4. Scan for strict-tier moments (grep partner's utterances).
5. Write a bash script (template: `/tmp/upload_*_clips.sh`) with `ffmpeg` cuts + Slack 3-step upload. **Always print `FILE_ID` so you can delete later.**
6. Run: `THREAD_TS=<ts> bash /tmp/upload_*_clips.sh`.

### 9.3 Delete a mis-posted clip
Requires the bot's `file_id` (printed at upload time, or listed via `files.list` if the bot has `files:read` scope — currently it doesn't):
```bash
curl -sS -X POST -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  --data-urlencode "file=$FILE_ID" https://slack.com/api/files.delete
```

### 9.4 Archive a Notion page (duplicates, wrong content)
```bash
curl -sS -X PATCH \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json" \
  -d '{"archived":true}' \
  "https://api.notion.com/v1/pages/<PAGE_ID>"
```

### 9.5 Redeploy the Cloudflare Worker after a src/worker.ts change
```bash
cd "$HOME/Platform <> Commercial Sync/automation/fathom-webhook"
npx wrangler deploy
```

### 9.6 Tail Cloudflare Worker logs
```bash
cd "$HOME/Platform <> Commercial Sync/automation/fathom-webhook"
npx wrangler tail
```

### 9.7 Add a new Fathom account (e.g. Ellena)
1. Ask them to generate a Fathom API key + share it.
2. Register a webhook on their account pointing to the Worker URL:
   ```bash
   cd "$HOME/Platform <> Commercial Sync/automation/fathom-webhook"
   node scripts/register-webhook.mjs --key <THEIR_KEY> --url https://fathom-webhook.<subdomain>.workers.dev/
   ```
3. Take the returned `whsec_…` and push to Cloudflare:
   ```bash
   echo "whsec_..." | npx wrangler secret put FATHOM_WEBHOOK_SECRET_ELLENA
   ```
4. Edit `src/worker.ts` to add `ellena` to the accounts array + the `Env` interface.
5. Edit `.github/workflows/process-meeting-webhook.yml`: add `FATHOM_ELLENA_KEY` env, extend the `$KEY` selector.
6. Add `FATHOM_ELLENA_KEY` to GitHub Secrets.
7. `npx wrangler deploy`.

---

## 10. Testing runbook (explicit)

### 10.1 Does the webhook chain fire hands-free?
```bash
cd "$HOME/Platform <> Commercial Sync/automation/suvera-automation"
gh workflow run test-webhook.yml
gh run watch $(gh run list --workflow=test-webhook.yml --limit 1 --json databaseId -q '.[0].databaseId')
```
**PASS**: job ends green with `::notice::Dispatched run id=…`.
**FAIL — Step 1**: Worker down / wrong URL / SSL cert issue.
**FAIL — Step 2**: Worker accepting unsigned requests (code bug).
**FAIL — Step 3 (missing secret)**: `FATHOM_WEBHOOK_SECRET_WILL` absent from GitHub Secrets.
**FAIL — Step 3 (signature failed)**: whsec in GitHub and Cloudflare diverged — re-sync.
**FAIL — Step 4 (no dispatch)**: Cloudflare → GitHub call failed. Most common cause: `GITHUB_PAT` lacks **Contents: Read and write** on suvera-automation. Check via local curl:
```bash
curl -sS -X POST \
  -H "Authorization: Bearer $PAT" -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" -H "Content-Type: application/json" \
  -d '{"event_type":"fathom_meeting_ended","client_payload":{"test":true}}' \
  https://api.github.com/repos/Will-Suvera/suvera-automation/dispatches
```
Expect HTTP 204 on success. 403 "Resource not accessible by personal access token" = wrong scope.

### 10.2 Does the full meeting pipeline work end-to-end?
```bash
# Pick a real recording_id from Fathom to test with
gh workflow run process-meeting-webhook.yml \
  -f account=will \
  -f recording_id=<RID> \
  -f title="Smoke test" \
  -f share_url="https://fathom.video/share/<SLUG>" \
  -f scheduled_start_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -f calendar_invitees_domains_type=one_or_more_external

# Watch it
gh run watch $(gh run list --workflow=process-meeting-webhook.yml --limit 1 --json databaseId -q '.[0].databaseId')
```
**PASS criteria:**
- Run exits green within ~16 minutes
- New Notion page in the Partner Meeting Library with matching Meeting ID
- New main post + thread in Slack `#partner-meetings`
- 5–10 `.mp4` clips uploaded as thread replies

Verify each layer:
```bash
# Notion: latest page with this rid
curl -sS -X POST -H "Authorization: Bearer $NOTION_TOKEN" -H "Notion-Version: 2025-09-03" \
  -H "Content-Type: application/json" \
  -d '{"filter":{"property":"Meeting ID","rich_text":{"equals":"<RID>"}}}' \
  https://api.notion.com/v1/data_sources/8115f0ee-00c8-488a-a05b-57726af0acf4/query | jq '[.results[] | {title:(.properties.Meeting.title[0].plain_text), url}]'

# Slack: you have to check in the app — bot lacks channels:history scope
```

### 10.3 Does the watchdog catch silent drift?
```bash
gh workflow run watchdog.yml
gh run watch $(gh run list --workflow=watchdog.yml --limit 1 --json databaseId -q '.[0].databaseId')
```
**PASS**: Slack post appears listing 24h external meetings with Planner mention counts, or `_No external meetings…_` if a quiet day.
**FAIL**: fix in the `fetch_meetings` jq expression — Fathom's schema uses `calendar_invitees_domains_type == "one_or_more_external"`, not `.invitees[]?.is_external`. This bug already bit once.

### 10.4 Does the daily summary workflow work?
```bash
gh workflow run daily-summary.yml
gh run watch $(gh run list --workflow=daily-summary.yml --limit 1 --json databaseId -q '.[0].databaseId')
```
**PASS**: either silent (no meetings today) or a single digest post in `#partner-meetings`.
**FAIL cases:** Claude Code max-turns exhausted (bump); Notion query wrong (check `Notion-Version: 2025-09-03`); cross-ref counts wildly wrong (refine prompt).

### 10.5 Does Fathom → real production work?
Ultimate test: have a short Fathom meeting with one external invitee where "Planner" is mentioned 3+ times. End the meeting, wait ~15 min. Expected:
- New Notion page in Partner Meeting Library
- New Slack main post in `#partner-meetings`
- Slack thread with 10 quotes + up to 10 clips

If nothing appears within 30 min, check in order:
1. Cloudflare Worker `npx wrangler tail` — did a webhook arrive?
2. `gh run list --repo Will-Suvera/suvera-automation --limit 5` — did a `repository_dispatch` fire?
3. Click into that run — did it exit quietly because of a filter, or fail?

---

## 11. Known gotchas

- **Share URLs are full URLs**, not slugs. Fathom's `/meetings` API returns `share_url: "https://fathom.video/share/..."`. Don't re-prepend the base path.
- **Notion 2025-09-03 API** uses data_sources (not just databases). `8115f0ee-…` is a `data_source` id, not a `database` id. Older `Notion-Version: 2022-06-28` can't see it. Create-page parent must be `{"type":"data_source_id", "data_source_id":"…"}`.
- **Claude Code GitHub App** must be installed on the repo — `anthropics/claude-code-action@v1` fails with 401 otherwise. Install: https://github.com/apps/claude.
- **OIDC permission required**: workflow YAML must have `permissions: id-token: write` or the action errors on boot.
- **Fine-grained PAT scopes** for dispatch: **Contents: Read and write** (not just Read). 403 "Resource not accessible by personal access token" = this.
- **Webhook has NO dedupe** — if two runs fire for the same recording_id, you get two Notion pages. Webhook fires once per meeting in prod, but manual replays can duplicate. Archive stale copies via Notion API (see 9.4).
- **Clip file_ids are lost** after upload unless you print them — the bot lacks `files:read` scope to list them after the fact. Always log `FILE_ID` when uploading.
- **ffmpeg max-turns budget** — a full-pipeline run on a long meeting can use 30–50 turns. `--max-turns 80` is the current ceiling; drop below 60 at your peril.

---

## 12. What's NOT automated yet

- Ellena's Fathom account (no API key shared yet)
- Camilla's account (intentionally excluded by scope — non-Planner work)
- Real-time Slack message edits (we post static content)
- Cross-account Slack channel routing (everything lands in `#partner-meetings`)
- Automated cleanup of orphan clips if a run partially fails (you do it manually via `files.delete`)

---

## 13. Provenance

Recent history that shapes the current design (why decisions were made):

- **Original design** (Apr 16): claude.ai scheduled triggers + GitHub Actions every 5 min firing the routine `/fire` endpoint. Worked but billed as API usage (pay-per-use).
- **Friday 2026-04-17 incident**: routine fired successfully (HTTP 200) for 3 days but produced no Notion pages — `allowed_tools` lacked MCP permissions. Silent failure.
- **Apr 21 afternoon**: hit Extra Usage spend cap — API-billed `/fire` calls exceeded the Anthropic account limit.
- **Apr 21 evening**: migrated to webhook + `CLAUDE_CODE_OAUTH_TOKEN` (subscription-funded). Built watchdog for silent-failure visibility. Tightened clip curation through two iterations.
- **Apr 21 late-evening → Apr 22**: tightened again (strict praise / direct feature asks only / detailed problems); added test-webhook smoke test; made daily-summary features-only + ranked by cross-ref count; raised pipeline timeout 20m → 35m after Chipping Norton was cut off mid-clip-upload. Thread permalinks were briefly mislabelled in a single user paste → re-uploaded to correct threads. Key lesson: always echo `file_id` to stdout at upload time — background-task capture has been unreliable at grabbing the first few lines.
- **Open blocker (Apr 22)**: the Cloudflare Worker's `GITHUB_PAT` currently has Contents: Read only, so `POST /repos/.../dispatches` returns 403 and the production webhook chain does not fire. Fix: edit PAT at https://github.com/settings/personal-access-tokens → Contents: Read and write. Until this is done, Fathom meetings will silently NOT be processed.
- **Next**: Ellena account onboarding, `files:read` bot scope for surgical clip management, optional real-time message edits, optional thread_ts registry on Notion pages so surgical re-curation doesn't need permalinks.
