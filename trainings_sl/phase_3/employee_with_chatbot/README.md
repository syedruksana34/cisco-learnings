# Employee Management System with Gemini chatbot

Same app as `../employee_management/employee.py`, plus an **Ask AI** assistant in the web UI (`/app`) powered by Gemini.
It answers questions about the application and its data by calling the app's own REST API
and running read-only SQL against the `employees` table.

## Setup

Create `employee_with_chatbot/.env` (never commit it):

```sh
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-3.8-flash          # optional, this is the default
MYSQL_USER=...
MYSQL_PASSWORD=...
MYSQL_DATABASE=employee_management
# Optional: a read-only MySQL account for the chatbot's SQL tool
# CHATBOT_DATABASE_URL=mysql+pymysql://readonly:pass@127.0.0.1:3306/employee_management
```

Run from this folder:

```sh
../employee_management/.venv/bin/uvicorn employee:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/app and click **Ask AI**.

## How it works

- `POST /api/chat` sends the conversation to Gemini with function-calling tools:
  REST lookups (all / by ID / by name / by designation), add, update, update salary, delete,
  and `run_sql_query` (single `SELECT` on `employees`, max 200 rows, read-only transaction, 5 s timeout).
- Write actions require the user to confirm first; "delete all" is not available to the bot.
- The directory table refreshes automatically when the assistant changes data.

## Gemini quota and availability

If the primary model returns HTTP 429 (quota/rate limit) or HTTP 500/503/504,
the app tries `GEMINI_FALLBACK_MODEL` (default: `gemini-3.5-flash`) and uses it
for a five-minute cooldown before trying the primary again. The chat displays
a notice when a fallback answers. Set `GEMINI_FALLBACK_MODEL=` to disable this.

Each tool round requires another Gemini request, so one chat question can
consume multiple requests. If both models are limited, check the project's
[usage and reset times](https://ai.dev/rate-limit). Daily quota exhaustion
requires waiting for the reset or enabling billing with sufficient quota;
restarting the app or retrying repeatedly does not restore quota.
