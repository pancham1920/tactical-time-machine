import { useEffect, useRef, useState } from 'react';
import { streamChat } from './api/chat.js';
import ChatInput from './components/ChatInput.jsx';
import ChatMessage from './components/ChatMessage.jsx';
import { updateAssistant } from './results.js';

const SUGGESTIONS = [
  { label: 'The big picture', question: 'How many matches are in the database?' },
  { label: 'Revisit the results', question: 'Show the five most recent matches in the database.' },
  { label: 'Explore player value', question: 'Which five players have the highest recorded market value?' },
];

export default function App() {
  const [messages, setMessages] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [progress, setProgress] = useState('');
  const [error, setError] = useState(null);
  const controllerRef = useRef(null);
  const scrollEnd = useRef(null);

  useEffect(() => () => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  useEffect(() => {
    scrollEnd.current?.scrollIntoView({ block: 'end', behavior: 'instant' });
  }, [messages, progress, error]);

  async function handleSend(message) {
    const question = message.trim();
    // The ref closes the gap before React has rendered the disabled button.
    if (!question || controllerRef.current) return;
    if (question.length > 2000) {
      setError('Keep your question to 2,000 characters or fewer.');
      return;
    }
    const controller = new AbortController();
    const assistantId = crypto.randomUUID();
    controllerRef.current = controller;
    setMessages(previous => [...previous, {
      id: crypto.randomUUID(), role: 'user', content: question,
    }, {
      id: assistantId, role: 'assistant', content: '', results: [], status: 'streaming',
    }]);
    setError(null);
    setIsStreaming(true);
    setProgress('Connecting to your analyst…');

    try {
      await streamChat({
        message: question,
        signal: controller.signal,
        onEvent: ({ event, data }) => {
          if (controllerRef.current !== controller) return;
          setMessages(previous => updateAssistant(previous, assistantId, event, data));
          if (event === 'connected') setProgress('Analyzing your question…');
          if (event === 'tool_call') setProgress('Querying football data…');
          if (event === 'tool_result') setProgress('Preparing your answer…');
          if (event === 'final_answer') {
            setProgress('Finishing…');
          }
        },
      });
    } catch (failure) {
      if (controllerRef.current === controller) {
        setMessages(previous => updateAssistant(previous, assistantId, 'error'));
        setError(controller.signal.aborted
          ? 'Request stopped. You can send another question.'
          : failure.message || 'Something went wrong. Please try again.');
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        setIsStreaming(false);
        setProgress('');
      }
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="./" aria-label="Tactical Time-Machine home">
          <span className="brand-mark" aria-hidden="true">T<span>↗</span></span>
          <span>Tactical<br /><span className="brand-secondary">Time-Machine</span></span>
        </a>
        <div className="sidebar-section">
          <p className="eyebrow">THE ANALYST ROOM</p>
          <div className="active-room"><span aria-hidden="true">◈</span> Football explorer</div>
        </div>
        <div className="pitch-panel" aria-hidden="true">
          <svg viewBox="0 0 200 250" fill="none">
            <rect x="15" y="15" width="170" height="220" rx="3" />
            <path d="M15 125H185M65 15V50H135V15M65 235V200H135V235" />
            <circle cx="100" cy="125" r="25" />
            <path className="pitch-route" d="M55 178L130 140L95 85L145 58" />
            <circle className="pitch-player" cx="55" cy="178" r="5" />
            <circle className="pitch-player" cx="130" cy="140" r="5" />
            <circle className="pitch-player" cx="95" cy="85" r="5" />
            <circle className="pitch-player" cx="145" cy="58" r="5" />
          </svg>
          <p>Follow the game.<br />Question the numbers.</p>
        </div>
        <div className="sidebar-footer">
          <span className="demo-tag">PROOF OF CONCEPT</span>
          <p>Built for curiosity.<br />Grounded in football data.</p>
        </div>
      </aside>

      <div className="main-panel">
        <header className="topbar">
          <span className="mobile-brand">Tactical Time-Machine</span>
          <span className="desktop-breadcrumb">Football explorer <span>/</span> Ask the analyst</span>
          <span className="header-tag">Historical data</span>
        </header>

        <main className="conversation-scroll" id="conversation">
          <div className="conversation-inner">
            {messages.length === 0 ? (
              <section className="welcome" aria-labelledby="welcome-title">
                <div className="welcome-kicker"><span /> YOUR FOOTBALL, IN FOCUS</div>
                <h1 id="welcome-title">Every match has a story.<br /><span>Find the numbers behind it.</span></h1>
                <p className="welcome-description">Explore matches, players, and market values with your football analyst. Ask a question. Let the data do the talking.</p>
                <div className="suggestions">
                  {SUGGESTIONS.map(({ label, question }, index) => (
                    <button key={label} className="suggestion" onClick={() => handleSend(question)} disabled={isStreaming}>
                      <span className="suggestion-number">0{index + 1}</span>
                      <span className="suggestion-label">{label}</span>
                      <span className="suggestion-question">{question}</span>
                      <span className="suggestion-arrow" aria-hidden="true">↗</span>
                    </button>
                  ))}
                </div>
              </section>
            ) : (
              <section aria-label="Conversation" role="log" aria-live="polite" aria-relevant="additions">
                {messages.map(message => <ChatMessage key={message.id} message={message} />)}
              </section>
            )}
            {isStreaming && (
              <div className="progress-row">
                <p role="status"><span className="progress-dot" aria-hidden="true" />{progress}</p>
                <button className="stop-button" onClick={() => controllerRef.current?.abort()}>Stop</button>
              </div>
            )}
            {error && <div className="error-message" role="alert">{error}</div>}
            <div ref={scrollEnd} />
          </div>
        </main>

        <footer className="composer-area">
          <div className="composer-inner">
            <ChatInput disabled={isStreaming} onSend={handleSend} />
            <p className="session-note">Each question is independent. History stays on this page only; the agent does not remember earlier questions yet.</p>
          </div>
        </footer>
      </div>
    </div>
  );
}
