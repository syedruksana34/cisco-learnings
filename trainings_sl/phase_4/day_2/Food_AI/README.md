# Savour House: smart ordering and restaurant assistant

A fictional FastAPI/MySQL restaurant demo with a browser interface and one tool-calling assistant.
There are no real payments or deliveries. The API works without AI; chat and document indexing require
a local Ollama instance or a Gemini/OpenAI API key with access to chat and embedding models.

## Architecture and design

* `app/main.py`: HTTP endpoints, authentication boundaries, exception handling and static hosting.
* `app/schemas.py`: Pydantic validation at the API boundary.
* `app/service.py`: shared business rules and transaction operations.
* `app/repository.py`: SQLAlchemy lookups and row locking (Repository pattern).
* `app/models.py`, `app/database.py`: relational persistence and unit-of-work sessions.
* `app/agent.py`: one bounded AI tool loop, action previews, and confirmation.
* `app/ai_provider.py`: configuration for local Ollama, Gemini, or OpenAI.
* `app/rag.py`: extract/chunk/embed/index/retrieve policy documents, with source metadata.
* `static/`: same-origin HTML/CSS/JavaScript frontend.

Responsibilities are separated (single responsibility); routes and the agent reuse the service rather
than duplicate business rules (dependency inversion and open/closed extension points). Constructor-injected
database sessions and the repository support substitution in tests. Confirmation executes through the
same business service **inside the database transaction**, rather than a second HTTP call: the action claim,
recheck, mutation and result commit atomically. Read tools use the fixed local REST API with the signed-in
identity. This is a deliberate deviation from the handbook's HTTP-only agent tool suggestion to avoid
an uncertain commit between a separate action claim and business request.

## Setup

Requires Python 3.10+, MySQL 8+, and internet access to install dependencies. From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Create a dedicated database and account using your MySQL administrator, then replace the placeholder
credentials in `.env`. For example (choose your own password):

```sql
CREATE DATABASE food_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'food_user'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON food_ai.* TO 'food_user'@'localhost';
```

For TCP connections MySQL account host matching depends on server configuration; grant the appropriate
local host for your installation. URL-encode special characters in the database password.

For local AI without API billing, install [Ollama](https://docs.ollama.com/linux), run its server, and pull
the models:

```bash
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
```

In `.env` set `AI_PROVIDER=ollama`, `OLLAMA_MODEL=qwen2.5:3b`, and
`OLLAMA_EMBEDDING_MODEL=nomic-embed-text`. Both models run locally. On a CPU, answers can take several
minutes. Keep Ollama running at `127.0.0.1:11434`; it is not exposed to the network. The model may
misunderstand requests, so check the exact preview before confirming any action.

Alternatively, for Gemini, create an API key in [Google AI Studio](https://aistudio.google.com/apikey) and add it to `.env`:

```env
AI_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-3.6-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
```

Gemini availability, free-tier eligibility, and rate limits depend on your project and region; requests
may incur charges. Chat text and retrieved policy excerpts are sent to the configured provider. Do not
send secrets or sensitive data in chat. For OpenAI, set `AI_PROVIDER=openai` and configure
`OPENAI_API_KEY`, `OPENAI_MODEL` and `OPENAI_EMBEDDING_MODEL`. Never commit `.env` or paste keys into chat.
Restart the app after editing `.env`.
When the primary Gemini model times out, is rate-limited, or returns a temporary server error, the app
restarts the unconfirmed chat operation with the configured fallback model and displays a notice.
Set `GEMINI_FALLBACK_MODEL=` to disable fallback. If both models are unavailable, the error is displayed;
model availability and quotas cannot be guaranteed.

Set a local demo password (at least 12 characters) and seed the database:

```bash
export DEMO_PASSWORD='choose-a-local-demo-password'
python -m app.seed
unset DEMO_PASSWORD
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/> or <http://127.0.0.1:8000/docs>. Sign in as `alice`, `bob`, or
`admin` using the demo password, or create a customer account using the sign-up screen. Sign-up usernames
use 3–100 ASCII letters, numbers, dots, underscores or hyphens; passwords use 8–128 printable ASCII
characters. Self-registration always creates a customer, never an administrator. Sign-in credentials
stay in browser memory, so a page refresh requires signing in again. Seed is repeatable and does not change existing users, passwords or
catalog; a new catalog receives 30 items and three example orders. The seeded portions shown in the UI
reflect those sample orders. For a different port, set `API_BASE_URL` to that same localhost origin.

For an existing catalog, run `python -m app.expand_menu` to add the 20 extra demo dishes and drinks.
Existing names, including disabled items, are left unchanged; running it again does not add duplicates.

Sign in as admin and use **Upload policy document** to index the fictional files in `knowledge_base/`.
Indexing creates embeddings with the configured provider and stores vectors under `data/chroma/`; MySQL stores document
versions. Uploading the same filename activates a new version. Back up both MySQL and `data/chroma/`
together. Policy questions cannot be answered from documents until they are indexed. Each provider and
embedding model has a separate vector collection: after changing providers or embedding models, an admin
must re-upload every policy document to index it again. Existing vectors are not deleted.

## Usage

Browse and filter the public menu. After sign-in, add items to the basket, place orders, and cancel orders
before preparation. Choose a category from the dropdown, and combine it with search, maximum price,
and dietary filters. Select vegetarian or non-vegetarian only; selecting both or neither shows both.
Menu cards show a green vegetarian or red non-vegetarian symbol. Administrators can create/update/disable menu entries and move orders through
`CONFIRMED → PREPARING → READY → DELIVERED`. Each order stores server-calculated price snapshots and
requires an `Idempotency-Key` header. My Orders shows each dish, quantity, and saved unit price. Dish
names reflect the current menu name, including for disabled items. Inventory updates are transactional
and use row locks on MySQL.

The 30 demo dishes include locally hosted, resized Wikimedia Commons photographs. The Photo credits
page names each photographer and links to the source and licence. These are illustrative photos, not photos of
actual dishes. Newly added or renamed menu items show “Photo unavailable” until a matching entry and
appropriately licensed image are added to `static/images/menu/photos.json` and the images folder.

Existing installations upgrading to item cancellation or order feedback must run `python -m app.migrate` once before
restarting the app. It creates the required tables without modifying existing orders. The database
account needs permission to create tables.

Signed-in customers can rate each of their own orders from 1 to 5 stars and optionally leave a comment
(up to 1,000 characters), regardless of order status. Feedback can be edited. It is private to the
customer and administrators; admins can load the latest 100 responses from the admin panel. Feedback is
not included in chatbot order data. Customers can ask the chatbot for highly rated food: it displays
aggregate averages of at least 4/5 based on non-cancelled, single-dish orders without item cancellations.
Multi-dish orders are excluded. This is an estimate based on order ratings, not a direct dish rating.
An average can be shown with just one rating, which may allow that customer's score to be inferred;
comments and customer names are not shown.

Ask Food Buddy to cancel a dish, for example “cancel one Tomato Soup from order 4.” If a dish occurs in
multiple orders, specify the order number; if multiple portions remain, specify how many to cancel. The
preview must be confirmed. Other dishes and portions stay in the order; cancelling every remaining item
cancels the order. The My Orders button cancels the entire remaining order. History shows the original
total and remaining total, and keeps cancelled portions visible. Names and categories reflect the current
menu rather than historical snapshots. Earlier AI-generated chat messages remain unchanged and may be
inaccurate; ask for your orders again to see current database records.

Open the **🤖 Food Buddy** button and try (a conversation is created automatically on the first message):

* “Show vegetarian dishes below INR 200.”
* “What does the cancellation policy say?”
* “Order one Masala Dosa.”
* As admin: “Create a vegetarian Soup in Starter for INR 80 with 10 portions.”

The chatbot can search/read catalog and orders, retrieve document evidence, propose orders and
cancellations, and propose admin catalog CRUD/status updates. All writes require explicit confirmation
using the button, expire after 15 minutes, are owner/role checked again, and recheck changed terms before
execution. Repeating a confirmation returns the recorded outcome. Session history and pending actions
survive restarts. Action previews and confirmation results are displayed as readable summaries rather
than raw JSON. Basic credentials stay in browser memory and are sent only to this same origin.
The assistant can interpret informal requests and spelling mistakes; close menu matches are suggestions,
not guaranteed matches. It may ask for clarification, and an order always requires explicit confirmation.
Order-history list replies are formatted directly from the signed-in user's live orders rather than
generated by the model. Before preparing an order, the app checks that the proposed dishes match the
request; if the request is ambiguous, name the dishes explicitly. Always review the preview, including
quantities, before confirming.

## Tests

```bash
python -m pytest -q
```

The default test suite uses a temporary SQLite database and mocked AI/Chroma. MySQL row-locking
and concurrent last-portion behavior require a **dedicated disposable** database named `food_ai_test`:

```bash
TEST_DATABASE_URL='mysql+pymysql://user:password@127.0.0.1:3306/food_ai_test' python -m pytest -q
```

**Tests drop all application tables in that test database.** Never point them at real data. Live AI
and embeddings are not exercised by these automated tests.

## Boundaries

This is a local training application, not a production deployment. A small per-process IP rate limiter
provides a basic local safeguard (120 requests/minute, or 20 AI message/upload requests/minute); it is not
shared across workers and does not trust forwarded IP headers. Use HTTPS beyond localhost, replace
demo accounts/passwords, and add network-level authentication/rate limiting, CSRF defenses, distributed
rate limits, database migrations, monitoring, retention/deletion policies, and production-grade document
index lifecycle management before any deployment. Basic authentication and the in-process code are not
a substitute for these controls. `.env` is loaded at process startup. A missing or unavailable AI service
returns an error and persists the failed chat turn; it never completes a pending write. The fictional
allergen guide is not a safety guarantee and cross-contact cannot be ruled out.
