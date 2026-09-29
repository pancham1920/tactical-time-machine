import { useEffect, useId, useRef, useState } from 'react';

export default function ChatInput({ disabled, onSend }) {
  const [draft, setDraft] = useState('');
  const inputId = useId();
  const textarea = useRef(null);
  const wasDisabled = useRef(disabled);

  useEffect(() => {
    if (wasDisabled.current && !disabled) textarea.current?.focus();
    wasDisabled.current = disabled;
  }, [disabled]);

  function submit(event) {
    event.preventDefault();
    const question = draft.trim();
    if (disabled || !question) return;
    onSend(question);
    setDraft('');
  }

  return (
    <form onSubmit={submit} className="composer">
      <label htmlFor={inputId} className="sr-only">Your football question</label>
      <textarea
        ref={textarea}
        id={inputId}
        value={draft}
        onChange={event => setDraft(event.target.value)}
        onKeyDown={event => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            submit(event);
          }
        }}
        disabled={disabled}
        maxLength={2000}
        rows={2}
        placeholder="Ask about a player, a match, a moment…"
        aria-describedby={`${inputId}-hint`}
      />
      <div className="composer-bottom">
        <span id={`${inputId}-hint`} className="input-hint">
          <span className="hidden sm:inline">Enter to send · Shift + Enter for a new line</span>
          <span className="sm:hidden">Ask one complete question</span>
          <span className="character-count">{draft.length}/2,000</span>
        </span>
        <button type="submit" className="send-button" disabled={disabled || !draft.trim()}>
          <span>Send</span><span aria-hidden="true">↗</span>
        </button>
      </div>
    </form>
  );
}
