# React chat and database results

This is the browser client for the existing FastAPI football agent. Run the API
on port 8000, then run `npm ci` and `npm run dev` in this directory. Open
`http://localhost:5173`. The [root README](../README.md) explains backend setup.

## Configuration

The client defaults to `http://127.0.0.1:8000`. Optionally copy `.env.example`
to `.env`, change `VITE_API_BASE_URL`, and restart the dev server. This value is
public and embedded at build time. Never store API keys in frontend variables.

## Files to read in order

| File | Responsibility |
| --- | --- |
| `src/main.jsx` | Mount React and import the stylesheet. |
| `src/App.jsx` | Own messages, loading/progress/error state, and request cancellation. |
| `src/components/ChatInput.jsx` | Own draft text; validate and submit it through a callback. |
| `src/components/ChatMessage.jsx` | Render one user or assistant message as escaped text. |
| `src/api/chat.js` | POST the question, read bytes, validate completion, and deliver events. |
| `src/api/sse.js` | Buffer text across chunks and decode complete SSE events. |
| `src/index.css` | Tailwind entry point and responsive page styles. |

## Request flow

1. `ChatInput` calls `onSend` with a trimmed question of up to 2,000 characters.
2. `App` appends the user message and creates an `AbortController`. A ref prevents
   a second submission even before React renders the disabled button.
3. `streamChat` sends `{ "message": "...", "conversation_id": "..." }` to
   `POST /chat/stream`. The same UUID is reused for follow-ups and saved in this
   tab's sessionStorage. On refresh, history is loaded before input is enabled.
4. A streaming `TextDecoder` preserves UTF-8 characters split across byte chunks.
5. The SSE parser keeps incomplete text until it has complete lines/events.
   It handles LF, CRLF, CR, comments, and multi-line `data` fields.
6. `connected`, `tool_call`, and `tool_result` update the progress message.
   Structured SQL results are validated and stored on this request's assistant
   message, deduplicated by tool-call ID. Each result gets a card, chart, or table.
7. `final_answer` fills in that assistant message. The answer arrives as a whole,
   not token-by-token. LangChain text content blocks are supported as well.
8. `complete` ends the successful request. HTTP errors, SSE errors, malformed
   events, and EOF without completion become visible failures.
9. Cleanup releases the stream reader and re-enables the composer. Stop and
   unmounting cancel the browser request. There are no automatic retries.

SQL results now appear alongside the answer. The backend still needs additional
work to stop model execution after a client aborts.

## State and limits

Visible messages live in component state; only the active UUID is saved in
sessionStorage. On refresh, `src/api/history.js` fetches and validates saved
messages and SQL results from `GET /conversations/{uuid}`. Cards, charts, and
tables use the same existing components. Interrupted turns are marked incomplete.
History loading never runs the model or replays a tool call. Input stays disabled
until restoration succeeds; failures offer Retry or New chat. Missing history
starts a fresh ID with a visible explanation. Stale loads are aborted/ignored.

The backend persists history and supplies bounded recent context to the model.
The browser still sends only the new question. New chat (disabled while a chat
request runs) clears messages/draft/errors and replaces the UUID without deleting
checkpoints. It can abandon a pending history load. Browser storage failures show
a warning. There is no saved-chat list or cross-device restoration. Conversation
IDs are not authentication: this remains a local prototype.

Plain text is intentional: output such as HTML is displayed literally rather
than injected into the page. Raw server exception details are not displayed by
the client. There is no analytics, external font, or paid frontend dependency.

## Verification

```bash
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

If Google Chrome is already installed, skip the browser download and run
`PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` instead.

The first command tests stream parsing and the HTTP helper with synthetic data.
Playwright starts Vite and intercepts chat requests, so tests need neither the
backend nor Gemini. It exercises desktop and mobile Chromium viewports and saves
layout screenshots under ignored `test-results/`. These checks do not prove
model correctness or a real Gemini connection.

For a manual live check, run both servers and ask: “How many matches are in the
database?” Confirm that progress ends with an answer. The number depends on your
dataset. If the API cannot be reached, check its port and `VITE_API_BASE_URL`.
If port 5173 is occupied, stop that dev server before starting another one.
