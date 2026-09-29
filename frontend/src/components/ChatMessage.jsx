export default function ChatMessage({ message }) {
  const isUser = message.role === 'user';
  return (
    <article className={`message ${isUser ? 'message-user' : 'message-assistant'}`}>
      <div className={`avatar ${isUser ? 'avatar-user' : ''}`} aria-hidden="true">
        {isUser ? 'Y' : 'T'}
      </div>
      <div className="min-w-0 flex-1">
        <p className="message-author">{isUser ? 'You' : 'Tactical analyst'}</p>
        {/* React escapes plain text, including HTML returned by the model. */}
        <div className="message-content">{message.content}</div>
      </div>
    </article>
  );
}
