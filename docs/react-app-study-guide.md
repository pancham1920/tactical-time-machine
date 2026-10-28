# Understanding App.jsx and its React design

[Open App.jsx](../frontend/src/App.jsx) alongside this guide. The actual filename
is `App.jsx`, not `App.js`; JSX lets JavaScript describe the interface using markup.

App is the chat coordinator. It remembers what should appear on screen, starts
requests, and connects streamed responses to the right message. It does not write
SQL or call Gemini directly. Those responsibilities belong to the Python backend.

## Start with the user requirements

Imagine building the chat without choosing any hooks yet. The user needs to open
a conversation, ask a question, see progress, receive results, stop a request,
refresh without losing visible history, and start a fresh chat.

Each requirement leads to a design choice:

| Requirement | Choice in App | Why it fits |
| --- | --- | --- |
| Display changing messages and progress | State | Changing these values must update the screen. |
| Remember an active request handle | Ref | Keep the same handle across renders without rendering because the handle changed. |
| Remember the conversation after refresh | Storage effect | React state disappears on refresh; browser storage holds the ID. |
| Show the saved conversation after refresh | History effect | An ID alone is not the actual messages; retrieve them from the backend. |
| Send when the user submits | Event handler | Submission is the direct cause of the request. |
| Start fresh when New chat is clicked | Event handler | Reset the conversation in response to that action. |
| Keep recent content visible | DOM ref and scrolling effect | Scroll a real browser element after React updates the screen. |
| Stop work when leaving | Effect cleanup | A removed component no longer needs its active request. |

This is the key distinction: calculate display values during rendering, respond
to user actions in handlers, and use effects to synchronize with external systems.
Not every network request belongs in an effect. Sending a question is a user
action; restoring the currently selected conversation is synchronization.

## How App connects to other files

```text
main.jsx → AccessGate.jsx → App.jsx
                             │
           ChatInput submits a question
                             ↓
                       handleSend
                             ↓
                       api/chat.js → Python backend
                             ↑             │
                             └── SSE events┘
                             ↓
                    results.js updates state
                             ↓
                ChatMessage → ResultView → table, card or chart
```

[AccessGate](../frontend/src/AccessGate.jsx) passes `userId` and `access` into App.
In local mode, the defaults are `userId = 'local'` and `access = null`.
The invitation code and browser session are passed to API helpers; the backend
still enforces authorization. A conversation ID does not itself grant access.

## Why useState is used

React calls the component function again to calculate the interface when its
state changes. State persists between those renders. A normal local variable
would be recreated on each call and changing it would not request a render.

| State value | Meaning and reason |
| --- | --- |
| `messages` | The visible user and assistant messages, including SQL results. |
| `initial` | The initial conversation decision: saved ID or new ID, and whether restoration is needed. |
| `conversationId` | The active conversation identity sent to the backend. |
| `restoreNeeded` | Whether saved history must be loaded before allowing another question. |
| `historyStatus` | Whether history is loading, ready, or failed. Drives loading and retry UI. |
| `historyAttempt` | A retry counter. Incrementing it makes the history effect run again. |
| `storageWarning` | Whether browser storage failed and a warning should appear. |
| `isStreaming` | Whether to show progress and disable conflicting actions. |
| `progress` | Human-readable text such as “Querying football data…”. |
| `error` | The current user-facing error, or null. |

`useState(() => initialConversation(storageKey))` uses a lazy initializer. React
uses it when initializing this component instance rather than repeating it on
every ordinary render. The helper returns an ID and a restoration flag; it does
not fetch messages. Development StrictMode can invoke initializers more than once
as a check, so initialization should not perform requests or writes.

Some values do not need their own state. `storageKey` is calculated from `userId`.
Whether to show the welcome screen is calculated from `messages.length === 0`.
Keeping duplicate state for such values would create extra things to synchronize.

## Why useRef is used

A ref is a stable container with a mutable `.current` property. Its value survives
renders, but assigning to it does not request a render.

| Ref | What current contains | Why it is not ordinary state |
| --- | --- | --- |
| `controllerRef` | The active chat AbortController, or null | It controls cancellation and identifies the request; it is not displayed. |
| `historyControllerRef` | The history request AbortController, or null initially | New chat needs access to a controller created inside the history effect. |
| `scrollEnd` | The DOM element at the bottom of the conversation, once mounted | Scrolling needs access to a browser element, not a displayed value. |

An AbortController provides a `signal` passed to a request and an `abort()` method
that signals cancellation. It does not contain the answer or start the request.

There are two request controllers because history loading and chat streaming are
different operations. They should not overwrite each other's cancellation handle.
The history ref can still point to a completed controller; it is used as a
cancellation handle, not as a reliable “history is loading” flag.

`isStreaming` and `controllerRef` are complementary. State updates the visible
buttons. The ref is updated immediately, preventing a second submission before
React has rendered the disabled button.

## The four effects

Effects run after React commits a render. Dependencies tell React when to repeat
synchronization. Before repeating an effect, React runs its previous cleanup;
cleanup also runs when the component is removed. StrictMode adds an extra initial
setup and cleanup cycle in development.

### Effect 1 saves the conversation ID

Dependencies: `conversationId` and `storageKey`.

Whenever either changes, write the current ID to `sessionStorage`. If storage
throws an error, show a warning. Only the ID is stored here, not the messages.

Without this effect, refreshing would lose the pointer to the current chat,
even if the backend still had its messages.

### Effect 2 restores the conversation

Dependencies: `conversationId`, `restoreNeeded`, `historyAttempt`, and `access`.

If restoration is unnecessary, return immediately. Otherwise, create a history
controller, show loading, and call `loadConversation()` with its signal and access
credentials. A successful response fills `messages` and marks history ready.
A missing conversation starts a new ID. A failed request shows an error and a
retry button; clicking retry increments `historyAttempt`.

The cleanup aborts the request. Both success and error callbacks check whether
it was aborted before updating state. This prevents an outdated history response
from filling a newly reset chat. After success, `restoreNeeded` becomes false;
the effect can run again but exits without fetching.

### Effect 3 cleans up the active chat request

Dependencies: an empty array.

The setup returns a cleanup function. When cleanup runs, it aborts the current
chat request and clears the ref. It does not abort the request immediately on
ordinary mounting.

The compact expression `useEffect(() => () => { ... }, [])` means “register a
function that returns a cleanup function.” It can be read more easily as:

```jsx
useEffect(() => {
  return () => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  };
}, []);
```

Browser cancellation does not guarantee that an external model operation already
started on the server immediately stops.

### Effect 4 scrolls to recent content

Dependencies: `messages`, `progress`, and `error`.

After the interface updates, call `scrollIntoView()` on `scrollEnd.current`.
The element is connected through `<div ref={scrollEnd} />`. Optional chaining
avoids calling the method while the element is unavailable.

Without this effect, new content could appear below the viewport. The trade-off
is that automatic scrolling may also pull someone away from older messages;
this implementation does not track whether the reader has intentionally scrolled up.

## Sending a question in plain English

`handleSend()` is an event handler, not an effect. Both the input component and
suggestion buttons call it.

1. Trim the question. Reject an empty or oversized question. Do not proceed if a
   request is active or saved history is not ready.
2. Create a controller and store it in `controllerRef.current`. Create a separate
   assistant message ID so incoming events have a specific message to update.
3. Add the user's message and an empty assistant placeholder. Keep existing messages.
4. Clear errors, turn on streaming state, and show initial progress.
5. Call `streamChat()` with the new question, conversation ID, credentials,
   cancellation signal, and an event callback. Do not send the whole history;
   the backend restores its own conversation state.
6. On each event, first verify that this controller is still the active one.
   Update the matching assistant through `updateAssistant()` and update progress.
7. On failure or cancellation, mark that assistant incomplete and show an error.
   Results received before the failure remain visible.
8. In `finally`, clear the active controller and loading indicators, but only if
   this request is still the active one.

`await streamChat()` waits for the stream to finish without freezing the browser.
Its event callback can run repeatedly while the asynchronous function is waiting.

| Event | Visible consequence |
| --- | --- |
| `connected` | Show that analysis has started. |
| `tool_call` | Show that football data is being queried. |
| `tool_result` | Attach SQL data to the assistant message. |
| `final_answer` | Put the answer text into that message. |
| `complete` | Mark the assistant response complete. |

`setMessages(previous => ...)` calculates from the latest available state.
It avoids overwriting newer messages with an older array captured by a callback.
The updater returns new arrays and objects, rather than mutating React state.

The identity check `controllerRef.current === controller` means “does the shared
active pointer still refer to this invocation's controller?” An older request
must not update or clear a newer request's UI.

## Starting a new chat and stopping a request

`startNewChat()` first checks `controllerRef.current`. If a chat request is active,
it returns without resetting anything. The New chat button is also disabled while
streaming; the handler check is a second guard.

Otherwise, it aborts any history fetch, disables restoration, sets history ready,
creates a fresh conversation ID, and clears messages, errors, and progress.
The storage effect then saves the new ID. This does not delete old server history.

The Stop button does something different: it calls `controllerRef.current?.abort()`.
The existing request's error handling and cleanup then update the screen. Stopping
does not immediately mean the backend is ready for another request; the API can
still reject a request while it is cleaning up the previous conversation operation.

## How the JSX reflects state

The returned JSX describes the screen for the current state. It does not itself
perform network requests during rendering.

| Condition or prop | UI decision |
| --- | --- |
| `messages.length === 0` | Show welcome text and suggested questions. |
| Messages exist | Render a ChatMessage for each message. |
| `historyStatus === 'loading'` | Show the restoration status. |
| `historyStatus === 'error'` | Show a retry button. |
| `isStreaming` | Show progress and Stop; disable New chat. |
| `error` is nonempty | Show an alert. |
| `isStreaming || restoreNeeded` | Disable ChatInput and suggestion submissions. |
| `storageWarning` | Explain that automatic restoration may be unavailable. |

`key={message.id}` gives React stable identities for list items. In contrast,
`<ChatInput key={conversationId} ... />` deliberately changes the child's identity
when starting a new conversation. React then recreates ChatInput, resetting its
local draft and other component state.

The draft belongs in ChatInput because typing is its local concern. App owns the
messages and request lifecycle because several children depend on those values.
That is the practical meaning of choosing where state should live.

## Why the responsibilities are split

| File | Responsibility |
| --- | --- |
| [App.jsx](../frontend/src/App.jsx) | Coordinate UI state, actions, and request lifecycle. |
| [ChatInput.jsx](../frontend/src/components/ChatInput.jsx) | Manage the draft and report submissions through a prop. |
| [api/chat.js](../frontend/src/api/chat.js) | Send the HTTP request and consume the response stream. |
| [api/sse.js](../frontend/src/api/sse.js) | Parse partial network text into complete SSE events. |
| [api/history.js](../frontend/src/api/history.js) | Find the initial ID, fetch history, and validate its structure. |
| [results.js](../frontend/src/results.js) | Validate, format, and transform data without network or DOM work. |
| [ChatMessage.jsx](../frontend/src/components/ChatMessage.jsx) | Render one message and its result components. |

This separation makes the parser and data transformations testable without React,
and keeps the chat component focused on coordinating user-visible behavior.
App does not currently need context, reducers, or memoization hooks merely because
they exist. If state transitions become harder to maintain, a reducer could group
them; if request logic is reused, custom hooks could extract it. Those are possible
future refactors, not requirements of the current implementation.

## Questions to check your understanding

1. Why does changing `controllerRef.current` not update the Stop button by itself?
2. Why does refreshing need both a stored conversation ID and a history request?
3. Why is sending a question a handler, while restoring history is an effect?
4. Why does New chat abort history loading but refuse to reset during chat streaming?
5. Why does each request need both a controller and an assistant message ID?

Answers: the button depends on state, not the ref; the ID is only a pointer;
submission is a user action while restoration synchronizes the selected conversation;
old history must not refill a new chat and active answers must not mix with resets;
the controller identifies/cancels work while the message ID identifies where its
results belong.
