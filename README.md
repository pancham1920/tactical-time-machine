# Tactical Time-Machine

Ask football questions in plain English. A Python agent queries read-only SQLite
and explains the results; React displays tool activity, tables, stat cards and charts.

**Local prototype:** persistent conversations, bounded SQL correction and tests.
Deployment configuration is prepared; no public hosted service is currently provided.
Uses historical data, not live scores or match predictions.

## See it working

![Captured model answer in the application](docs/media/answer.png)

[Short demo recording](docs/media/demo.webm) · [Recording provenance](docs/demo.md)

The recording replays captured live Gemini responses against fictional sample data.
It demonstrates the real frontend, not a currently running hosted backend.

## Architecture

```text
User → React → FastAPI /chat/stream → LangGraph → Gemini
                                      ↕ tool calls
                                Read-only SQLAlchemy → SQLite
           ← SSE tool activity, SQL results and final answer ←
```

- **Python:** FastAPI, Pydantic, LangGraph, LangChain, SQLAlchemy, SQLite.
- **JavaScript:** React, Vite, Tailwind CSS, Recharts, Playwright.
- Conversation checkpoints are separate from football data; the browser sends
  only new messages. SQL errors trigger a bounded correction loop.
- Read-only connections, SQL restrictions, execution limits and invite controls
  reduce risk; this is not a production security certification.

## Measured results — incomplete live run

40 numeric questions have independently specified expected values, verified by
reference SQL on a fictional database. On October 15, 2026, Gemini 2.5 Flash
completed **3/40** correctly, then hit a **provider quota error** on question four.
The remaining 36 were not run.

SQL succeeded for **3/3 returned tool results**. Exact numeric correctness was
**3/4 attempted (75%)**, including the failed request. Median attempt latency:
**3.01 seconds**. These preliminary results cannot establish general accuracy.
[Method, failures and raw report](docs/evaluation.md).

## Try with tiny fictional data

Requires Python 3.12 and Node 22.12+ (or a supported newer release).

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
python -m scripts.create_sample_db
```

Set `GEMINI_API_KEY` in a local `.env` (see `.env.example`); never commit it.
Live answers require your own Gemini access and available quota. Offline tests
and sample database creation require no API key. The builder refuses to overwrite
an existing database. Start the backend from the repository root:

```bash
AUTH_MODE=local FOOTBALL_DB_PATH=build/sample/football_vault.db CONVERSATION_DB_PATH=build/sample/conversations.db python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd frontend
npm ci
VITE_AUTH_MODE=local VITE_SAMPLE_DATA=true npm run dev
```

Open the Vite URL. Ask **“How many matches are in agent_match_view?”** (expected: 8).
Local mode is for your own machine; do not expose it publicly.
[Full dataset and operations](docs/implementation.md) · [Data sources](DATA_SOURCES.md).

## Verify

```bash
venv/bin/python -m unittest discover -s tests
venv/bin/python -m scripts.evaluate_agent
cd frontend
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

[CI](.github/workflows/ci.yml) runs Python tests, offline reference verification,
frontend tests/build and desktop/mobile browser tests without API secrets.
[Live evaluation](docs/evaluation.md) is explicitly opt-in.

## Limitations and reuse

The tiny sample is not a performance benchmark. Eight additional qualitative
analyst review cases are not included in the numeric score.

**Code licensing remains undecided; no open-source license has been selected.**
Upstream data has separate terms in [DATA_SOURCES.md](DATA_SOURCES.md).
