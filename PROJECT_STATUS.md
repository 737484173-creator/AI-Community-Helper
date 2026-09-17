# AI Community Operation Center - Project Status

## Completed

- Phase 1: Modular project structure and SQLite database
- Phase 2: SDK.xlsx FAQ import
- Phase 3: Discord bot message capture
- Phase 4: Guided FAQ support flow
- Phase 5: FAQ-first AI support service
- Phase 6: Player feedback analysis
- Phase 7: Community event management
- Phase 8: Event analytics collection
- Phase 9: Daily and weekly report generation
- Phase 10: Streamlit operation dashboard
- Dashboard polish: date/status filters and CSV export for operations pages
- Discord slash commands: help, faq, ticket, report, event
- Operations packaging: manage.py, PowerShell scripts, deployment guide
- Dashboard simple password authentication
- Report Markdown and CSV export
- Structured Poll/Survey/Quiz options for scheduled events
- Future VIP Operation Center extension tables and repositories
- Pending ticket internal notes for operator handoff
- Custom date range report generation
- Poll analytics mapped from reactions to configured options
- Event retrospective reports for single-event postmortems

## Local Services

Dashboard:

```bash
python manage.py dashboard --port 8502
```

URL:

```text
http://localhost:8502
```

Discord bot:

```bash
python manage.py bot
```

Required environment variables:

```text
DISCORD_BOT_TOKEN
OPENAI_API_KEY optional
COMMUNITY_DB_PATH optional
```

## Current Database

Default path:

```text
data/community.db
```

Imported FAQ:

```text
Account: 18
Login: 5
Payment: 27
Total: 50
```

## Validation

Latest automated test result:

```text
67 passed
```

## Next Recommended Work

- Add operator-facing report templates for incident/event retrospectives
- Add incident-specific report templates for complaint spikes or outages
