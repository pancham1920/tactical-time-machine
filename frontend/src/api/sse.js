/** Parse SSE text incrementally. One network chunk can contain partial events. */
export function createSseParser(onEvent) {
  let buffer = '';
  let eventName = '';
  let dataLines = [];

  function acceptLine(line) {
    if (line === '') {
      if (dataLines.length) {
        let data;
        try {
          data = JSON.parse(dataLines.join('\n'));
        } catch {
          throw new Error('The server sent an unreadable stream event. Please try again.');
        }
        onEvent({ event: eventName || 'message', data });
      }
      eventName = '';
      dataLines = [];
      return;
    }
    if (line.startsWith(':')) return; // SSE comments / keep-alive messages.
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') eventName = value;
    if (field === 'data') dataLines.push(value);
  }

  function drain(final = false) {
    while (true) {
      const newline = buffer.search(/[\r\n]/);
      if (newline < 0) return;
      // A CR at the end of a chunk could be the first half of CRLF.
      if (!final && buffer[newline] === '\r' && newline === buffer.length - 1) return;
      const width = buffer.slice(newline, newline + 2) === '\r\n' ? 2 : 1;
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + width);
      acceptLine(line);
    }
  }

  return {
    push(text) {
      buffer += text;
      drain();
    },
    finish() {
      drain(true);
      if (buffer || dataLines.length || eventName) {
        throw new Error('The response was interrupted. Please try your question again.');
      }
    },
  };
}
