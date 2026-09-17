# AI Community Operation Center

AI-driven Discord community operation backend for game operation teams.

## Phase 1 Scope

- Modular project structure
- SQLite database initialization
- Repository layer for core tables
- Basic tests for database CRUD

## Setup

```bash
python -m venv .venv
pip install -r requirements.txt
```

## Initialize Database

```bash
python manage.py init-db
```

By default, the SQLite database is created at:

```text
data/community.db
```

You can override it with:

```bash
set COMMUNITY_DB_PATH=path/to/community.db
```

## Run Tests

```bash
pytest
```

## Import FAQ Excel

The importer supports both normal header rows:

```text
Category | Question | Answer | Subcategory | Keywords | Enabled
```

and SDK-style prefixed rows:

```text
Category: Login | Question: Cannot login | Answer: Please restart the game.
```

```bash
python manage.py import-faq "C:/Users/Administrator/Desktop/SDK.xlsx"
```

## Run Discord Bot

Create a `.env` file or set environment variables based on `.env.example`, then run:

```bash
python manage.py bot
```

Required Discord configuration:

```text
DISCORD_BOT_TOKEN
```

Optional Dashboard configuration:

```text
DASHBOARD_PASSWORD
```

Optional Discord history recovery configuration:

```text
DISCORD_AUTO_BACKFILL_HOURS=24
```

On startup the bot imports readable server-channel messages from this lookback
window. After a live connection loss, it resumes from five minutes before the
disconnect time. Set the value to `0` to disable automatic history recovery.
Imported messages are deduplicated by Discord message ID and never trigger DM
replies or support workflows.

The bot currently supports:

- Connects to Discord
- Ignores bot and webhook messages
- Saves every user-authored server channel message into SQLite for activity metrics
- Creates a `users` record using `discord_user_id`
- Opens guided FAQ support
- Searches FAQ and replies with official answers
- Creates manual support tickets
- Schedules community events
- Generates daily and weekly reports

To backfill readable Discord history and refresh saved daily/weekly reports:

```bash
python manage.py backfill-discord --since 2026-07-30
```

The bot account needs `View Channel` and `Read Message History` in the channels
that should be included. Message Content Intent must also be enabled for the bot.
The import is safe to rerun because Discord message IDs are deduplicated.

Slash commands:

```text
/help
/faq question
/ticket issue
/report report_type
/event title content event_type publish_time repeat_rule
```

## Guided FAQ Flow

When a player sends a help trigger such as:

```text
help
/help
support
faq
Chinese equivalents for customer service, help, issue, and support
```

the bot shows a guided support flow:

1. Select issue category
2. Select specific FAQ question
3. Receive the official answer from the imported FAQ knowledge base
4. Choose `Solved` or `Need manual support`

If the player chooses manual support, or no FAQ category is available, the system
creates a record in `pending_tickets`.

Operators can add internal notes to pending tickets. Notes are stored separately
in `pending_ticket_notes` so the original player issue is preserved.

## AI-assisted FAQ Matching

Phase 5 adds direct message handling before GPT is required:

- Player sends a normal support question
- System searches imported FAQ by category, question, answer, and keywords
- If a confident FAQ match is found, the official FAQ answer is returned
- If no confident match is found and the message looks like a support issue, a
  `pending_tickets` record is created for manual handling

The OpenAI client is wrapped in `app/ai/ai_client.py`, but local tests do not
call GPT. Set `OPENAI_API_KEY` only when you are ready to enable GPT-backed
rewriting or classification.

## Feedback Analysis

Phase 6 adds structured player feedback capture. Messages classified as:

```text
BUG
SUGGESTION
EVENT_FEEDBACK
COMPLAINT
```

are analyzed and written to `feedback` with:

```text
category
feature
keywords
sentiment
priority
status
```

Supported first-stage feedback categories:

```text
BUG
GAMEPLAY_SUGGESTION
BALANCE_ISSUE
REWARD_ISSUE
EVENT_SUGGESTION
OTHER
```

## Community Event Management

Phase 7 adds scheduled community event publishing.

Supported event types:

```text
Poll
Survey
Announcement
Quiz
```

Poll, Survey, and Quiz events can include structured options. Options are stored
on the event and rendered as A/B/C choices when published.
Analytics map matching reactions back to configured options and identify the
winning option in reports.

Supported repeat rules:

```text
none
daily
weekly:friday:18:00
```

Create an event by inserting through `EventRepository` with `status="Scheduled"`.
When the Discord bot starts, it also starts a scheduler that checks due events
every 30 seconds. Once an event is published:

- one-time events become `Published`
- repeating events stay `Scheduled` and receive the next `publish_time`
- an `event_analytics` record is created
- `discord_message_id` is saved on the event

## Event Analytics

Phase 8 adds activity performance collection. When the Discord bot is running,
the scheduler also checks published event messages every 60 seconds and updates:

```text
participant_count
reaction_count
poll_result_json
```

Analytics are linked through:

```text
events.discord_message_id
event_analytics.event_id
```

`poll_result_json` stores reaction counts as JSON, for example:

```json
{"A": 12, "B": 8}
```

## AI Report Generator

Phase 9 adds daily and weekly community reports based on real database metrics:

```text
messages
feedback
pending_tickets
events
event_analytics
```

The Discord bot scheduler generates:

- the completed previous day's report at 00:05
- the completed previous week's report every Monday at 00:08

You can also generate reports manually:

```bash
python manage.py report daily
python manage.py report weekly
python manage.py report custom --start "2026-07-30 00:00:00" --end "2026-07-31 23:59:59"
```

Reports are saved into the `reports` table.

## Streamlit Operation Dashboard

Phase 10 adds a Streamlit dashboard:

```bash
python manage.py dashboard --port 8502
```

In restricted environments, use:

```bash
python manage.py dashboard --port 8502
```

Set `DASHBOARD_PASSWORD` in `.env` to require login. Without it, the Dashboard
runs in local development mode.

Pages:

```text
Dashboard
Chat Monitor
Feedback Center
Pending Issues
Event Management
Reports
FAQ Management
```

Reports can be downloaded as Markdown, and report lists can be exported as CSV.
Custom reports can be generated from the Reports page by selecting a start and
end date.

Event retrospectives can be generated from Event Management or the CLI:

```bash
python manage.py event-retrospective 1
```

More deployment and operations details are available in `DEPLOYMENT.md`.

## VIP Operation Center and AE Data Source

The VIP Operations and VIP Red Black pages use a local snapshot synchronized
from AE project 24 (`巨兽战场-正式-全球`). Run a refresh from the VIP Operations
page or from the command line:

```bash
python manage.py sync-ae-vip
```

The command requires an authenticated `ae-cli` in this project directory. It
uses the user property `#account_id` as the stable role identity, keeps players
whose cumulative non-sandbox USD recharge is at least 1000, and calculates the
previous seven complete days without today. Server IDs 1, 6, 11, 14, 19, and
20 are classified as old servers; an empty CPS group is classified as organic.
An explicitly uploaded Excel workbook temporarily overrides the AE snapshot,
and the bundled workbook remains available as a fallback when no snapshot is
present.

The database also contains game-side profile extension tables:

```text
player_profiles
vip_profiles
risk_profiles
```

These tables use `player_id` and `server_id` for future Discord-to-game account
binding. AE VIP snapshots are stored separately in `vip_ae_snapshots`, with sync
history in `vip_ae_sync_runs`.
