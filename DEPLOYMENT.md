# Deployment and Operations Guide

## 1. Environment Setup

Create `.env` from `.env.example`:

```text
DISCORD_BOT_TOKEN=your_discord_bot_token
OPENAI_API_KEY=optional_openai_api_key
COMMUNITY_DB_PATH=data/community.db
DASHBOARD_PASSWORD=change_this_before_sharing
LOG_LEVEL=INFO
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## 2. Initialize Database

```bash
python manage.py init-db
```

Windows shortcut:

```powershell
.\scripts\init_db.ps1
```

## 3. Import FAQ

```bash
python manage.py import-faq "C:/Users/Administrator/Desktop/SDK.xlsx"
```

Windows shortcut:

```powershell
.\scripts\import_faq.ps1 "C:/Users/Administrator/Desktop/SDK.xlsx"
```

## 4. Run Dashboard

```bash
python manage.py dashboard --port 8502
```

Windows shortcut:

```powershell
.\scripts\run_dashboard.ps1 8502
```

Dashboard URL:

```text
http://localhost:8502
```

If `DASHBOARD_PASSWORD` is configured, the Dashboard requires login. If it is
not configured, the Dashboard runs in local development mode and displays a
warning in the sidebar.

## 5. Run Discord Bot

```bash
python manage.py bot
```

Windows shortcut:

```powershell
.\scripts\run_bot.ps1
```

The bot starts:

- Discord message listener
- FAQ guided support
- Slash commands
- Event scheduler
- Event analytics collector
- Daily and weekly report scheduler

## 6. Manual Report Generation

```bash
python manage.py report daily
python manage.py report weekly
```

Windows shortcut:

```powershell
.\scripts\generate_report.ps1 daily
.\scripts\generate_report.ps1 weekly
```

## 7. Recommended Local Run Order

```bash
python manage.py init-db
python manage.py import-faq "C:/Users/Administrator/Desktop/SDK.xlsx"
python manage.py dashboard --port 8502
```

Start the Discord bot in a separate terminal:

```bash
python manage.py bot
```

## 8. Operational Notes

- SQLite is intended for phase-one local operation.
- Do not expose Streamlit to the public internet without adding authentication.
- Set `DASHBOARD_PASSWORD` before sharing the Dashboard on a local network.
- Current version does not bind Discord users to game accounts.
- `users.player_id` and `users.server_id` are reserved for future VIP Operation Center integration.
