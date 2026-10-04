# Tactical Time-Machine

An AI football analytics application that answers natural-language questions using
Gemini, LangGraph, and a local SQLite database. The agent can request a SQL tool,
read its results, and explain the answer. FastAPI exposes both a JSON response
and a stream of tool activity and the final answer. A React chat interface shows
the conversation and live progress in the browser.

**Status:** Blocks 1–8 implemented as a local prototype, including tab refresh
history restoration. Deployment is not implemented. No hosted demo is currently
provided; the deployment target is a $0 proof of concept with free-tier limits.

## What is implemented

- CSV ingestion in chunks, normalized table/column names, and query indexes.
- `agent_match_view`, which joins games with club names for score queries.
- A Gemini → SQL tool → Gemini loop orchestrated by LangGraph.
- Basic SQL validation, structured errors, and a maximum of 100 returned rows.
- Chat request validation and SSE events for tool calls, results, and answers.
- A responsive React chat UI with suggested questions, progress, cancellation,
  and error recovery. Answers are displayed as plain text.
- SQL-backed tables, numeric stat cards, and conservative category/value bar charts
  with Recharts. Empty, failed, and truncated query results are clearly labelled.
- Automated tests using synthetic SQLite data and mocked agent responses.

The application uses downloaded data; it does not fetch live scores. Answers
depend on the coverage and quality of the supplied dataset.

## Architecture and stack

```mermaid
flowchart LR
    Client[React chat UI / API client] --> API[FastAPI]
    API --> Agent[LangGraph agent]
    Agent <--> Gemini[Google Gemini]
    Agent --> Tool[SQL tool: validation and row cap]
    Tool --> DB[(SQLite)]
    DB --> Tool
    Tool --> Agent
    Agent --> API
    API --> Response[JSON answer or SSE events]
    CSV[Local CSV files] --> Seed[pandas seeding script]
    Seed --> DB
```

| Layer | Technology |
| --- | --- |
| Language | Python, JavaScript/JSX, CSS, SQL |
| Frontend | React, Vite, Tailwind CSS |
| AI and orchestration | Google Gemini, LangChain, LangGraph |
| Data | pandas, SQLAlchemy, SQLite |
| API | FastAPI, Pydantic, Uvicorn |
| Transport | HTTP JSON and Server-Sent Events (SSE) |
| Tests | unittest, FastAPI TestClient / HTTPX, Node test runner, Playwright |

SQLite keeps the local data setup simple. `agent_match_view` reduces the joins
the model needs to generate. LangGraph makes the tool loop explicit. SSE fits
the current one-way delivery of progress and answers to a client.

## Local setup

Use Python 3.12 (the version used for local verification). Run these commands
from the project root after downloading or cloning the source:

```bash
python3.12 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

If `.env` does not already exist, copy `.env.example` to `.env`. On macOS/Linux,
the following command preserves an existing file:

```bash
cp -n .env.example .env
```

Edit `.env` locally:

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Required for real agent requests; supply your own Google API key. |
| `GEMINI_MODEL` | Optional model override; the code defaults to `gemini-2.5-flash`. Choose a model available to your API project. |

Agent requests use Google's API and may incur usage charges. User messages and
tool results are sent to Gemini. `.env` is ignored by Git; `.env.example` contains
placeholders only.

### Prepare the football database

The raw CSVs and generated database are not distributed with the source. Download
the CSV archive from [Football Data from Transfermarkt on Kaggle](https://www.kaggle.com/datasets/davidcariboo/player-scores)
and extract the 12 CSVs into `data/`. Kaggle lists this dataset as CC0: Public
Domain. See [DATA_SOURCES.md](DATA_SOURCES.md) for attribution, expected filenames,
and version caveats. A fresh clone needs this separate data download for real
football queries; the automated tests run without it.

After placing the CSVs in `data/`, build the database:

```bash
python scripts/seed_db.py
```

This creates `football_vault.db`, indexes, and `agent_match_view`, and prints a
sample query. **Re-running the script replaces matching tables** in the existing
database; keep a backup if you have local changes. Expect substantial disk and
processing requirements for the full dataset.

### Start the server

```bash
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

The API runs at `http://127.0.0.1:8000`. Interactive FastAPI documentation is
available at `http://127.0.0.1:8000/docs`. `/health` does not require a key or a
seeded database; football questions do.

### Start the frontend

Use Node.js 22.12+ (verified locally with 22.14) or another version supported
by `frontend/package.json`. Keep the API running and open a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Visit **http://localhost:5173**. Ask a full question, or choose a suggested one.
You should see progress followed by the final answer. Use Enter to submit and
Shift + Enter for a new line. Stop cancels the browser request; it does not
guarantee that an already-running backend/model operation is cancelled.

The API defaults to `http://127.0.0.1:8000`. To override it, copy
`frontend/.env.example` to `frontend/.env` and edit `VITE_API_BASE_URL`, then
restart Vite. **Frontend environment variables are public: never place a
Gemini key in them.** Keep the real key only in the root backend `.env`.

Use `localhost:5173` for the frontend because that exact origin is allowed by
the current API CORS configuration. Vite uses a strict port so a conflict
fails clearly rather than silently moving to an unauthorized origin.

The browser sends only the latest question plus a conversation UUID. The backend
restores recent context from SQLite checkpoints. Refresh reloads this tab's
saved messages and query results. New chat starts fresh without deleting old checkpoints. SQL results appear
alongside the answer. See [frontend/README.md](frontend/README.md)
for the component layout and streaming design.

## Try the backend

With the server running, use a second terminal:

```bash
curl --fail-with-body http://127.0.0.1:8000/health

curl --fail-with-body --request POST http://127.0.0.1:8000/chat \
  --header 'Content-Type: application/json' \
  --data '{"message":"How many matches are in the database?"}'

curl --no-buffer --fail-with-body --request POST http://127.0.0.1:8000/chat/stream \
  --header 'Content-Type: application/json' \
  --data '{"message":"How many matches are in the database?"}'
```

Example from a previously tested local snapshot (counts depend on your data):

```text
event: connected
data: {"message": "Agent started", "conversation_id": "9ac12a9b-d2df-4fce-bc53-c037f45b7626"}

event: tool_call
data: {"tools": ["execute_sql"]}

event: tool_result
data: {"tool_call_id":"example-count","tool":"execute_sql","result":{"columns":["matches"],"rows":[{"matches":86983}],"truncated":false}}

event: final_answer
data: {"answer": "There are 86,983 matches in the database."}

event: complete
data: {}
```

This is a terminal demo; no React frontend is needed. The stream delivers graph
updates, not individual answer tokens or private model reasoning. Tool selection,
query aliases, wording, and the number of tool calls may vary.

## API contract

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Returns `{"status":"ok"}`; checks HTTP liveness only. |
| `GET /conversations/{uuid}` | Returns a UI-safe projection of saved messages and SQL results without invoking Gemini. Unknown IDs return 404; busy threads return 409. |
| `POST /chat` | Runs the graph and returns `{"answer":"...","conversation_id":"..."}`. |
| `POST /chat/stream` | Runs the graph and returns `text/event-stream`. |

Both chat endpoints accept:

```json
{"message":"How many matches are in the database?","conversation_id":"9ac12a9b-d2df-4fce-bc53-c037f45b7626"}
```

`message` must be a string of 1–2,000 characters. Invalid bodies receive HTTP
422. Whitespace-only strings and malformed conversation UUIDs are rejected.
The conversation ID is optional: omission generates a fresh UUID, and an unknown
valid UUID starts a new thread. Reuse the returned ID for follow-ups. A failed `/chat` agent run
returns HTTP 502 with a generic message. A streaming failure after the response
starts is an SSE `error` event rather than a new HTTP status. Concurrent requests
for the same conversation receive HTTP 409 before a response stream starts.
An oversized/invalid current exchange returns HTTP 413 on `/chat` or an SSE
`error` with `code: "context_limit"` on `/chat/stream`; start fresh or narrow the question.

| SSE event | Data shape / meaning |
| --- | --- |
| `connected` | `{"message":"Agent started","conversation_id":"..."}`; resolved thread ID, not a dependency health check. |
| `tool_call` | `{"tools":["execute_sql"]}`; tools requested by Gemini. |
| `tool_result` | `{"tool_call_id":"...","tool":"execute_sql","result":{...}}`; result contains columns, rows, and truncated, or a sanitized error. One event per tool message. |
| `final_answer` | `{"answer":"..."}`; final model output. |
| `error` | `{"message":"..."}`; workflow failed; no `complete` follows. |
| `complete` | `{}`; workflow ended successfully, not a guarantee of answer correctness. |

Use `fetch()` with a streaming response reader for this POST endpoint; native
browser `EventSource` does not send this JSON POST request. Each SSE event ends
with a blank line. Parse the event's `data` JSON once; `result` is already an
object. This replaces Block 5's nested JSON-string contract: restart the backend
and refresh the frontend together. Local CORS permits `http://localhost:5173`.

### Conversation memory (local prototype)

API startup opens a LangGraph async SQLite saver at `conversation_memory.db`,
separate from football data. The saver closes on shutdown; the file and its
SQLite sidecars are ignored by Git. Checkpoints include user messages, model
messages and tool results. They survive a backend restart when the client reuses
the same conversation ID. The terminal smoke test remains nonpersistent.

Run exactly **one backend worker/process** against this prototype. An in-process
guard serializes each conversation by rejecting overlap (409); it does not
coordinate multiple workers. Graph/model execution and checkpoint access are
asynchronous; SQL tools may still finish work already dispatched to a thread
after cancellation. No automatic HTTP retries or request deduplication are added.

`AGENT_CONTEXT_MAX_CHARS` defaults to 64000. This is an approximate serialized
character budget, **not** a Gemini token count. The model receives the system
prompt, the current complete tool exchange, and a recent contiguous suffix of
complete turns; 8000 characters are reserved for tool/schema overhead. An older
interrupted turn ends that suffix. Oversized current exchanges fail explicitly
rather than splitting tool-call/result pairs. Stored history is not trimmed;
checkpoint size grows until a separate retention/deletion policy is implemented.

The frontend saves only its active UUID in `sessionStorage`, not message bodies.
Refresh restores this tab's history through `GET /conversations/{uuid}` before
enabling the composer. The endpoint uses the same busy guard as chat writes and
returns `Cache-Control: no-store`. It projects user text, final assistant text,
structured query results, and incomplete-response status; raw graph metadata,
system messages, intermediate tool-call arguments and thinking blocks are excluded.
Missing history starts a new chat with an explanation. Network/storage failures
leave input blocked with Retry and New chat options; they never silently reuse
unseen context. A still-running chat may return 409 until its operation stops.

New chat clears the screen/draft and replaces the stored ID; it does not delete
old checkpoints and is disabled during an active chat request. It can cancel a
pending history load. Storage-disabled browsers can chat but show a warning that
refresh restoration is unavailable. Session storage is tab-scoped; a duplicated
tab may inherit its ID, so the backend busy guard remains necessary. There is no
saved-chat list, cross-device history, pagination, or deletion interface yet.

**Privacy:** conversation IDs are not authentication. Anyone with an ID and API
access could read its history or append to that thread. Keep the
app local until ownership checks, access control and retention are implemented.
Checkpoints are not encrypted; don't submit sensitive information to this demo.

## Automated tests

Install the development dependencies and run:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The tests use a temporary SQLite database with generated data and mocked graph
responses. They do not need a Gemini key, a local football dataset, or a running
server, and do not call Gemini. They cover SQL rejection, query errors and row
caps, API input validation, response handling, and SSE success/error sequences.
HTTP tests use [FastAPI's documented TestClient](https://fastapi.tiangolo.com/tutorial/testing/).
They do not measure model answer accuracy or network streaming latency.

Analyst prompt tests also verify that the schema, evidence rules, and response
guidance reach the model on initial and post-tool calls without altering message
history. These are wiring/regression tests, not proof of model compliance.
`tests/fixtures/analyst_review_cases.json` contains eight review scenarios and
acceptance criteria. Normal questions can be reviewed through the app; the two
`controlled_tool_result` cases require a controlled model-evaluation setup, not
pasting fake tool data into the user input. The file is a review checklist, not
an automated live evaluator. Live evaluation is opt-in and may consume API quota.

Frontend parser/API tests and production build:

```bash
cd frontend
npm ci
npm test
npm run build
```

Browser interaction tests (desktop and mobile viewports):

```bash
npx playwright install chromium
npm run test:e2e
```

Alternatively, with Google Chrome already installed, skip the download and use
`PLAYWRIGHT_CHANNEL=chrome npm run test:e2e`.

Browser tests start Vite automatically and mock the API responses. They test
submitting questions, preventing duplicate requests, recovery after errors,
interrupted streams, cancellation, text escaping, and responsive layout. No
Gemini calls or real football data are used. A live Gemini-backed browser
question is a separate manual integration check.

Block 5 was manually verified in Chrome by the project owner. Automated memory
tests use actual temporary SQLite checkpoints and mocked model responses to check
reopen/restart persistence, isolation, tool evidence, context selection and busy
guard cleanup. Browser tests mock HTTP responses. Live Gemini follow-up quality
remains a separate manual check: ask for a team's five recent matches, then ask
"How many of those did they win?" without repeating the team.

Current verification: 40 Python tests, 28 frontend unit tests, 24 desktop/mobile
Chrome browser tests, and the frontend production build passed without live
Gemini calls. The Python suite emits an existing TestClient/httpx deprecation
warning; migrating that test dependency is separate from conversation memory.

## Source layout

```text
scripts/seed_db.py       CSV import, indexes, and match view
src/agents/config.py    Gemini client configuration
src/agents/prompts.py   Analyst instructions and known schema
src/agents/graph.py     Agent/tool graph and message state
src/agents/memory.py    Persistent checkpoint connection lifecycle
src/agents/context.py   Tool-safe bounded model context
src/agents/history.py   UI-safe checkpoint history projection
src/tools/db_tools.py   SQL validation, execution, and JSON formatting
src/api/main.py         HTTP endpoints and SSE formatting
tests/                  Offline SQL and API tests
frontend/src/           React UI, HTTP client, and SSE parser
frontend/tests/         Parser/API tests and browser interaction tests
main.py                 Terminal agent smoke test
DATA_SOURCES.md          Dataset provenance and preparation
```

## Roadmap

| Block | Scope | Status |
| --- | --- | --- |
| 1 | CSV seeding, SQLite indexes, match view | Implemented |
| 2 | Gemini client and LangGraph agent | Implemented |
| 3 | SQL tool and agent/tool loop | Implemented with basic guards |
| 4 | FastAPI JSON and SSE endpoints | Implemented prototype |
| 5 | React, Vite, and Tailwind chat UI | Implemented; automated browser checks use mocked responses |
| 6 | Tables, stat cards, and charts | Implemented; live-data review pending |
| 7 | Richer tactical commentary | Prompt and offline tests implemented; live answer-quality review pending |
| 8 | Persistent conversation memory | Agent memory and tab-refresh history restoration implemented; live review pending |
| 9 | Explicit, bounded SQL correction/retry policy | Planned; tool errors already return to the model |
| 10 | Deployment and integration testing | Planned |

## Current limitations

- SQL protection uses keyword checks, not a SQL parser or a database-enforced
  read-only connection. There is no query timeout or table allowlist. The row
  cap limits returned data, not query execution cost.
- The API has no authentication or rate limiting. CORS and conversation UUIDs
  are not authorization. Keep this prototype local until access controls exist.
- The API supports a single worker, not distributed conversation coordination.
  Cancellation cannot guarantee termination of an already-running SQL thread or
  remote model operation. Every tool message is emitted separately.
- Schema instructions are a hand-maintained subset of the database. Missing
  data and model mistakes can still produce incomplete or incorrect answers.
- Python dependencies are not pinned yet. Frontend dependencies have exact
  versions and a committed npm lockfile. Python dependency locking and CI remain
  follow-up work.

## Data and licensing

Raw data, SQLite files, virtual environments, and real credentials are excluded
by `.gitignore`. See [DATA_SOURCES.md](DATA_SOURCES.md) for provenance and usage
status. No open-source license has been selected for the project code yet.
Dataset licensing must be established separately.

[ANALYSIS.md](ANALYSIS.md) is an archived, pre-implementation data assessment;
its old application-readiness statements are not the current project status.
