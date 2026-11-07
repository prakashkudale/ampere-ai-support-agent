# Ampere AI Support Agent

FastAPI support assistant with documentation answers and citations, fictional account diagnostics,
persistent conversations, and privacy-safe tickets delivered through a mock Discord adapter.

## Run (Python 3.12)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
Copy-Item .env.example .env
# Edit .env: use a matching provider key, base URL, and supported model ID.
.\.venv\Scripts\python scripts/ingest_docs.py
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 for the optional chat UI or `/docs` for interactive API testing.
Use one server process. Environment variables override `.env`; never commit real keys.
Direct Anthropic users should set `ANTHROPIC_BASE_URL=https://api.anthropic.com` and their
own available model ID. Custom Anthropic-compatible providers are supported.

## Example request

```powershell
$body = @{conversation_id='demo'; request_id='m1'; message='My agent is broken'} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/chat -Method Post -ContentType 'application/json' -Body $body
```

Next send `rahul@example.com` with the same conversation ID and a new request ID.
Responses include `answer`, `sources`, `outcome`, and nullable `ticket_id`. Outcomes are
`answered`, `needs_clarification`, `escalated`, and `escalation_pending`. Repeating an
identical request ID replays its result; conflicting content returns 409.

## Design

- **Model:** Anthropic Python SDK, tested with the configured third-party provider's
  `claude-sonnet-5-5` identifier. Native schemas handle intent, grounded answers and
  contextual phrasing. Routing permits one correction attempt; tool execution is bounded.
- **Search:** approved Ampere docs are downloaded, chunked, and indexed in SQLite FTS5.
  Query expansion supports common wording. Returned citations must match retrieved,
  approved source URLs. Unsupported questions remain uncertain. Rerun ingestion to refresh.
- **Lookup:** initialization seeds unique rows for Priya (running) and Rahul (offline,
  missing API key). `Store.get_agent_status(email)` uses parameterized SQL. Other emails
  return not found. An account problem is required before lookup; email is not authentication.
- **Memory:** SQLite stores messages, issue state, email context, and guidance progress
  per conversation ID. Separate chats stay separate; locks serialize each conversation.
  Follow-ups distinguish clarification, completed steps, failures, and new topics.
- **Tickets:** an explicit human request escalates immediately; unresolved issues get
  follow-ups first. Tickets are saved before delivery, unique per issue, and omit raw
  chat/personal details. Retries reuse tickets. `MOCK_DISCORD_RESULT=failure` leaves them
  pending; `success` simulates acceptance. Restart after changing settings. No real Discord
  messages are sent. For a new retry attempt, use a new request ID and request the handoff.

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python scripts/smoke_test.py
```

The smoke script makes billable provider calls. `scripts/evaluate_conversations.py`
contains the larger live suite. See [TEST_RESULTS.md](TEST_RESULTS.md) and
[LIMITATIONS.md](LIMITATIONS.md) for recorded results and practical boundaries.
