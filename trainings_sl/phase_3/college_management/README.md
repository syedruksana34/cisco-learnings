# CampusFlow

A college/university administration web application built with **Python, Django 5.2, MySQL 8+, and vanilla JavaScript**. The responsive frontend uses authenticated JSON REST APIs for every management operation. Flask and SQLite are no longer used to serve the application.

## Features

- Django administrator authentication, hashed passwords, eight-hour database-backed sessions, CSRF protection, and login throttling.
- Dashboard with student/faculty/course counts, department distribution, recent students, attendance rate, outstanding fees, and collection totals.
- Create, view, edit, delete, search, filter, and export students, faculty, departments, courses, enrollments, attendance, and fees.
- Searchable, paginated tables, accessible forms, and responsive mobile navigation.
- Optional student and faculty contact numbers, available in forms, tables, search, APIs, and CSV exports.
- Local RAG campus assistant using Ollama, an administrator-managed PDF/TXT/FAQ knowledge library, retrieved-source citations, and live aggregate statistics. No cloud API key required.
- Per-semester course capacity enforcement using MySQL transactions and row locks.
- Unique enrollments, active-student checks, protected attendance history, and daily attendance validation.
- Fee totals, cumulative payments, remaining balances, and automatically calculated payment/overdue statuses.
- Protected relationships: deleting a linked record returns an actionable error instead of cascading silently.
- Django ORM models, versioned schema migrations, and optional demo data.

## Run locally

Requires **Python 3.10+**, **MySQL 8.0.16+**, and pip/venv. Use MySQL's InnoDB storage engine.

### 1. Install dependencies

On Ubuntu, the native MySQL driver needs these build prerequisites:

```bash
sudo apt-get install python3-venv python3-dev default-libmysqlclient-dev build-essential pkg-config
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2. Configure MySQL

Create a dedicated database and account using a MySQL administrator. Replace `YOUR_DATABASE_PASSWORD` with a separate strong database password:

```sql
CREATE DATABASE campusflow CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
CREATE USER 'campusflow'@'localhost' IDENTIFIED BY 'YOUR_DATABASE_PASSWORD';
GRANT ALL PRIVILEGES ON campusflow.* TO 'campusflow'@'localhost';
-- Optional, for the automated test suite only:
GRANT ALL PRIVILEGES ON test_campusflow.* TO 'campusflow'@'localhost';
```

Copy `.env.example` to `.env` and set your connection details:

```dotenv
MYSQL_DATABASE=campusflow
MYSQL_USER=campusflow
MYSQL_PASSWORD=YOUR_DATABASE_PASSWORD
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
```

Django loads `.env` automatically. Environment variables override values in the file. The file is ignored by Git. There is **no SQLite fallback**: invalid MySQL configuration results in an explicit connection error.

On this workstation, the ignored local `.env` is configured for the existing `ruksyed615` MySQL account through `/var/run/mysqld/mysqld.sock`, without a database password. Only the new `campusflow` and `test_campusflow` schemas were granted to that account; unrelated databases were not changed. For another machine, use your own configuration. The application login is separate from the MySQL account.

The database uses `utf8mb4_bin` to retain case-sensitive identifiers from the original application. Emails are normalized to lowercase before saving. Changing the database collation can change uniqueness behavior.

### 3. Initialize and start Django

From this directory, with the virtual environment activated:

```bash
python manage.py migrate
python manage.py seed_demo
python manage.py create_admin --username admin
python manage.py runserver 127.0.0.1:5000
```

Skip `seed_demo` if you want an empty application or already have records. It requires empty management tables and never overwrites existing records. `migrate` is safe to rerun.

`create_admin` securely prompts for a password and confirmation; use at least 12 characters. Visit **http://127.0.0.1:5000** and sign in with the account you created.

### Sign up from the login screen

Select **Create an account**, choose a unique username, and enter and confirm a password of at least 12 characters. Django also rejects common, entirely numeric, and overly similar passwords. Successful registration signs you in immediately, with no approval required.

**Local demo only:** Self-registered accounts receive the same full campus management access as existing administrators (`is_staff=True`), but are not Django superusers. Anyone who can reach open sign-up can access and modify the campus data. Do not expose this mode publicly or use it with real student data.

`ALLOW_OPEN_SIGNUP` defaults to enabled when `DJANGO_DEBUG=1` and disabled otherwise. Set `ALLOW_OPEN_SIGNUP=0` in `.env` to disable both the form and API; restart the server after changing configuration. Disabling sign-up does not revoke existing accounts.

Use `manage.py` for all application commands. Standard Django `manage.py runserver` defaults to port 8000 unless a port is specified.

### Local administrator credentials

- Username: `admin`
- Password: `Sharuk@14122003`

These are the requested local credentials, not an automatically created account. Run `python manage.py create_admin --username admin` and enter this password when prompted to configure the account.

**Local use only:** This section contains a plaintext password. Do not publish, share, or commit this file with these credentials included.

To change an existing Django administrator's password:

```bash
python manage.py changepassword admin
```

### Existing workstation data

The existing dataset is stored in MySQL: 4 departments, 12 students, 4 faculty members, 5 courses, 12 enrollments, 60 attendance records, and 12 fee records. The legacy SQLite backup and one-time importer were removed after verifying all academic records against MySQL.

Legacy administrator accounts and browser sessions were not imported. Create Django administrators with `create_admin`.

## Configuration and persistence

Academic records, administrator accounts, login attempts, sessions, and extracted knowledge chunks persist in MySQL. Use your MySQL backup tools and access policies.

A generated Django signing key is retained in `instance/.secret` with owner-only permissions unless `SECRET_KEY` is configured. Keep it private and stable across restarts. Django sessions invalidate when migrating from Flask, even when reusing the existing signing key.

| Variable | Purpose |
|---|---|
| `MYSQL_DATABASE` | Application database; default `campusflow` |
| `MYSQL_USER`, `MYSQL_PASSWORD` | MySQL credentials; configure for your installation |
| `MYSQL_HOST`, `MYSQL_PORT` | MySQL address; defaults `127.0.0.1`, `3306` |
| `MYSQL_UNIX_SOCKET` | Optional local socket path, instead of TCP |
| `MYSQL_TEST_DATABASE` | Dedicated test database; default `test_campusflow` |
| `DJANGO_DEBUG` | `1` for local static-file serving; set `0` in production |
| `ALLOW_OPEN_SIGNUP` | Local-demo immediate-access registration; defaults to `1` in debug mode, otherwise `0` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames; defaults to localhost addresses |
| `SECRET_KEY` | Stable, high-entropy signing key instead of the generated local key |
| `COOKIE_SECURE=1` | Send session and CSRF cookies only over HTTPS, not local HTTP |
| `CSRF_TRUSTED_ORIGINS` | Optional comma-separated trusted HTTPS origins |
| `TIME_ZONE` | Calendar timezone; default `UTC` |
| `RAG_ENABLED` | `1` (default) uses retrieval and Ollama; `0` explicitly selects the legacy rule-based assistant |
| `OLLAMA_URL` | Local HTTP loopback address only; default `http://127.0.0.1:11434`; proxies and redirects are not used |
| `OLLAMA_MODEL` | Installed local generation model; default `llama3.2:3b` |

## Using the application

1. Create departments before students, faculty, or courses.
2. Create faculty and optionally assign an instructor to a course.
3. Enroll active students into courses using a consistent semester label, such as `Fall 2026`.
4. Record attendance against a specific enrollment and class date.
5. Add a fee and update **Amount paid** as payments arrive.

All amounts are USD. **Amount paid is the cumulative amount received**, not an additional payment. The app tracks balances; it does not process payments or maintain a payment transaction ledger.

An enrollment with attendance cannot change student, course, or semester until its attendance records are removed. Completed enrollments may receive retrospective attendance; dropped enrollments may not. Existing enrollments are retained when a student's status changes, but inactive students cannot create or reactivate an active enrollment.

Attendance rate is `(Present + Late) / all attendance records`, including absent/excused records in the denominator. The overview includes all semesters. Recently added students are ordered by creation ID. Fee statuses are Paid, Overdue, Partial, or Pending; an unpaid balance becomes overdue after the due date. Attendance validation uses the configured `TIME_ZONE`; browser fee indicators use the browser's local date.

Search and filters apply to the current table. **Export all CSV** exports all records of that type, not only the current page or search results. Formula-like text is escaped for spreadsheet safety.

## Campus assistant

After signing in, select the **robot icon** at the bottom right (labelled **Campus assistant**). By default it now uses **retrieval-augmented generation (RAG)**: relevant local passages are retrieved first, then an Ollama language model generates an answer using those passages.

### Start local AI

Install Ollama using the [official Linux instructions](https://docs.ollama.com/linux). In separate terminals:

```bash
# Terminal 1: localhost only; disable Ollama cloud features.
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 ollama serve
# Terminal 2: download the local model once (several GB of disk space required).
ollama pull llama3.2:3b
python manage.py migrate
python manage.py runserver 127.0.0.1:5000
```

On this workstation Ollama is installed in `~/.local/share/campusflow-ollama/bin/ollama`, with models in `~/.local/share/campusflow-ollama/models`. To start it again, use the full binary path and set `OLLAMA_MODELS` to that models directory alongside the two environment variables above. It is not installed as a system service.

The default model runs on CPU if no supported GPU is available. The first request may take longer while the model loads. Each model call times out after 90 seconds. Structured JSON and source numbers are validated; malformed or title-only answers are retried once with the same evidence and a corrective instruction (up to two model calls). If both answers fail validation, an explicit error is returned, never a hidden rule-based fallback. Connection failures are not retried. To deliberately use the old offline rules instead, set `RAG_ENABLED=0` and restart Django.

### Add and use knowledge

1. Select **Upload / knowledge** in the robot chatbot. The knowledge library opens **inside the same chat panel**, not in a separate dialog. Your conversation and draft question are preserved.
2. Enter a title and policy/FAQ text, **or** select one UTF-8 `.txt` or text-based `.pdf` file.
3. Select **Add knowledge**. Chunks persist immediately in MySQL and are available to the next query; no separate indexing job is needed. The panel returns to your conversation with an upload confirmation. The new source becomes the current document in this tab, so you can immediately say `summarize`, even if you previously discussed another topic. Use **Back to chat** (or Escape) to return without uploading; your source draft is preserved until sign-out or reload.
4. Ask a question such as `When does the library close?` after adding your actual library schedule. No university policies or schedules are invented or pre-seeded.
5. Expand **Retrieved sources** under the answer to inspect supporting excerpts and PDF page numbers. **View** shows a source's indexed chunks; **Remove** excludes it from future queries.

Uploads are limited to **5 MB**, **100 PDF pages**, and **50,000 extracted characters** per source. Only extracted text, source titles, filenames, and PDF page numbers are retained; original files are discarded. Scanned/image-only PDFs need OCR before uploading; encrypted, empty, unsupported, or invalid documents are rejected. Only upload trusted documents; PDF parsing is not sandboxed.

Retrieval uses local **BM25-style lexical ranking**, common typo aliases, and fuzzy word matching, with overlapping 900-character chunks and at most four relevant passages per question. For an overview that names a document, it selects substantial passages in reading order across that document rather than favoring short headings or footers; longer documents are sampled within the same four-passage limit. Entering only a document title also requests a short overview; spacing differences such as `Cisco phase 3` and `cisco phase3` are accepted. A specific question still uses relevance ranking rather than overview sampling. This is RAG without an external vector database or embedding service. It is intended for a small campus knowledge library, not huge document collections; synonym-only semantic matches and complex multi-document questions may be missed.

Built-in workflow guides and freshly queried aggregate counts, fee totals (USD), and attendance rates across all semesters are also available as sources. Individual student/faculty records are **not** retrieved. The model cannot execute database changes, tools, or payments. Source numbers are checked against the actual retrieved passages; titles, excerpts, and links come from the server, not from model-generated URLs.

**AI answers can still be wrong.** Citation validation does not prove that every generated claim follows from its source. Verify important facts against the displayed excerpts. Documents are untrusted reference text, and the model is instructed not to follow embedded commands; prompt instructions are not a complete defense against malicious documents.

All administrators share the knowledge library. It has the same access boundary as campus management, including any accounts created through open sign-up. Do not upload student records, passwords, or confidential material: knowledge text can be returned to any administrator. Questions and retrieved excerpts go only to your configured loopback Ollama instance; use local models with cloud features disabled as above.

Conversation messages and the current document ID are held only in the current tab (up to 40 displayed messages) and clear on reload or sign-out. In RAG mode the last **three completed user/assistant turns** are sent to local Ollama to understand follow-ups such as `in short paragraph give overview` or `make it shorter`. Failed requests are not added to this history. A newly uploaded source takes precedence over previous conversation for short follow-ups. Answers citing a single document make it the current document; newly named subjects use a fresh retrieval query rather than inheriting that selection. A follow-up without an available topic asks for clarification. Sources are retrieved again for every turn, so removed documents are not reused as evidence; prior answers are not treated as source material. A document removed in another tab produces an explicit unavailable-source error. Removing a source does not erase excerpts already displayed in a tab or recent answer text held in that tab's history; reload to clear them. Chat messages are not saved to MySQL. Normal Django/Ollama logging still applies.

## REST API

The REST routes and JSON resource shapes are retained from the original application, so the existing interface remains compatible. Django provides routing, ORM, authentication, sessions, and CSRF middleware; no Flask dependency is required.

All management endpoints require an active Django user with `is_staff=True`. Every unsafe request requires `X-CSRF-Token`, including login and logout. PATCH is not supported; use PUT with all editable fields.

### Authentication

1. `GET /api/session` sets the CSRF cookie and returns `{"user": null, "csrf_token": "..."}`.
2. `POST /api/login` with `{"username": "admin", "password": "..."}`, the CSRF cookie, and CSRF header.
3. Save the **new** token returned by login and retain both cookies (`csrftoken` and `sessionid`).
4. `POST /api/logout` clears the session and rotates the CSRF token. Fetch `/api/session` again before another login.

When open registration is enabled, `POST /api/signup` accepts `{"username": "...", "password": "...", "confirm_password": "..."}` with the CSRF cookie/header. It returns `201` with the same user/token shape as login and creates a signed-in session. Extra fields and authenticated registration attempts are rejected. No client-supplied role flags are accepted.

Tokens are Django CSRF tokens, not the previous Flask token format. Do not reuse tokens or session cookies from the old application.

```bash
curl -c cookies.txt http://127.0.0.1:5000/api/session
# Replace TOKEN with csrf_token from above; use your own password.
curl -b cookies.txt -c cookies.txt \
  -H 'Content-Type: application/json' -H 'X-CSRF-Token: TOKEN' \
  -d '{"username":"admin","password":"YOUR_PASSWORD"}' \
  http://127.0.0.1:5000/api/login
curl -b cookies.txt http://127.0.0.1:5000/api/dashboard
```

Ten failed logins for a username within 15 minutes temporarily block further attempts for that username.

### Management routes

`resource` is one of `departments`, `students`, `faculty`, `courses`, `enrollments`, `attendance`, or `fees`. Routes do not use trailing slashes.

| Method | Route | Response |
|---|---|---|
| GET | `/api/dashboard` | Counts, finance, attendance, departments, recent students, outstanding fees |
| POST | `/api/chatbot` | Body `{"message": "Campus summary"}`, with optional `history` and `document_id` in RAG mode; response `{"reply": "...", "links": [...], "mode": "rag", "sources": [...]}` and a `document_id` for single-document answers; legacy rule-based mode returns `mode: "local"` |
| GET | `/api/knowledge` | Source metadata list, active mode, and model name |
| POST | `/api/knowledge` | JSON `{"title": "...", "text": "..."}` or multipart `title` and one `file`; returns `201 {"data": {...}}` |
| GET | `/api/knowledge/<id>` | Metadata and extracted chunks with PDF page numbers |
| DELETE | `/api/knowledge/<id>` | Removes document and chunks; `204` |
| GET | `/api/<resource>` | `{"data": [...], "total": N}` |
| GET | `/api/<resource>/<id>` | `{"data": {...}}`, including display labels |
| POST | `/api/<resource>` | `201 {"data": {...}}` |
| PUT | `/api/<resource>/<id>` | `{"data": {...}}`; complete editable record required |
| DELETE | `/api/<resource>/<id>` | `204` with no body |
| GET | `/api/export/<resource>` | CSV download of all records |

List routes support `?q=text` and exact filters for applicable fields: `department_id`, `student_id`, `course_id`, `enrollment_id`, `status`, `semester`, and `date`. The API returns all matching rows; the browser handles eight-row pagination. The local edition is intended for small datasets.

### Editable fields

All fields except `phone_number` are required in POST/PUT; `faculty_id` may be `null`. IDs are JSON integers, not numeric strings. Do not send `id` or joined/display fields in write requests.

Student and faculty `phone_number` values are optional strings containing exactly 10 digits (`0-9`), such as `9876543210`. Country codes, spaces within numbers, punctuation, and letters are rejected. Leading zeros are preserved. Send `""` to clear a number; omitting the field on PUT preserves the existing number. Existing records start with blank numbers. Numbers are not required to be unique.

| Resource | Editable fields |
|---|---|
| departments | `name`, `code` |
| students | `student_number`, `first_name`, `last_name`, `email`, `phone_number` (optional), `department_id`, `year` (1-8), `status` |
| faculty | `employee_number`, `first_name`, `last_name`, `email`, `phone_number` (optional), `department_id`, `title` |
| courses | `code`, `name`, `department_id`, `faculty_id`, `credits` (1-12), `capacity` (1-1000) |
| enrollments | `student_id`, `course_id`, `semester`, `status` |
| attendance | `enrollment_id`, `date` (`YYYY-MM-DD`), `status` |
| fees | `student_id`, `description`, `amount_cents`, `paid_cents`, `due_date` (`YYYY-MM-DD`) |

Student statuses: `Active`, `Graduated`, `On leave`. Enrollment statuses: `Enrolled`, `Completed`, `Dropped`. Attendance statuses: `Present`, `Absent`, `Late`, `Excused`.

Money uses integer cents; `125050` means `$1,250.50`. Fees must be positive, and paid amounts must be between zero and the total. Text fields are limited to 200 characters. Student numbers, employee numbers, emails (within each person type), department names/codes, course codes, student/course/semester combinations, and enrollment/date combinations must be unique.

Errors use `{"error": "Explanation"}`: 400 invalid input, 401 sign-in required, 403 CSRF failure, 404 missing resource, 405 unsupported method, 409 duplicate/linked data, 413 request too large, 429 login throttling, 502 invalid generated answer, and 503 database or local model unavailable.

The chatbot requires the same administrator session and CSRF header as other write endpoints, even though its behavior is read-only. Messages must contain 1-500 characters. In RAG mode an optional `history` array accepts up to six messages (three complete turns), alternating `{"role": "user", "content": "..."}` and `{"role": "assistant", "content": "..."}`. User history content is limited to 500 characters and assistant content to 6,000. Empty content, incomplete turns, system/tool roles, and extra fields are rejected. Optional `document_id` accepts a positive integer knowledge source ID or `null`; it scopes short follow-ups, not explicit new topics. Invalid or removed source IDs return HTTP 400. Omitting both fields remains supported; legacy rule-based mode accepts only `message`.

RAG `sources` entries contain `number` (model citation), `title`, `document_id` (null for built-in/live sources), `page` (PDF page or null), `excerpt`, and a stable source `key`. Questions with no relevant evidence return an explicit no-evidence answer with empty sources rather than invented facts.

## Tests

Run the integration suite against **MySQL**, not a substitute SQLite test database:

```bash
python manage.py test test_college_management campus.test_rag --noinput
python manage.py check --database default
python manage.py makemigrations --check --dry-run
node --check static/app.js
```

The suite creates and destroys only the configured `test_campusflow` database. Never point `MYSQL_TEST_DATABASE` at a database containing real data. The test account needs CREATE/DROP and table permissions on this separate test schema.

Tests cover all seven CRUD workflows, authentication and CSRF rotation, login throttling, validation, capacity (including simultaneous requests for the last seat), attendance history, financial aggregation, filtering, CSV safety, and demo/admin commands.

RAG tests additionally cover real PDF text extraction, UTF-8 text ingestion, upload/text limits, rejected files, chunking, typo-tolerant retrieval, reading-order document overviews, bounded/validated conversation history, nested follow-ups, topic changes, deleted-source exclusion, aggregate-only context, authentication/CSRF, validated citations, one-attempt answer repair, local-only model addresses, and explicit unavailable/invalid model errors. Automated tests mock Ollama for repeatability and do not require model downloads; real-model smoke checks are separate.

Node is only needed for the optional JavaScript syntax check, not to run the application.

## Deployment boundaries

This is a local **administrator application**, not a production-certified student information system. It intentionally has one administrator role and no student/faculty self-service, timetable scheduling, examinations/grades, email delivery, online payment processing, or audit trail.

Before exposing it to real users, deploy `campusflow.wsgi:application` or `campusflow.asgi:application` with a production server behind HTTPS, disable debug mode, configure secure cookies/allowed hosts and a managed signing key, run `python manage.py collectstatic`, and serve static files through the web server. Add institutional authorization/auditing, backup policies, and privacy/compliance safeguards. Never expose Django's development server or commit `.env`, the instance directory, credentials, or real student data.
