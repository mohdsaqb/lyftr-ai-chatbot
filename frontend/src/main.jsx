import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { sendMessage } from "./chat";
import "./style.css";

const sessionId = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte =>
  byte.toString(16).padStart(2, "0")
).join("");

function AssistantReply({ reply, metadata }) {
  const fields = [
    ["Source", "meta-source", metadata.resolution_source],
    ["Model", "meta-model", metadata.model],
    ["Latency", "meta-latency", `${metadata.latency_ms} ms`],
    ["Input tokens", "meta-input-tokens", metadata.input_tokens],
    ["Output tokens", "meta-output-tokens", metadata.output_tokens],
  ];
  return (
    <article className="reply" data-testid="assistant-message" aria-label="Lyftr reply">
      <div className="speaker"><span className="mini-mark" aria-hidden="true">L</span> Lyftr</div>
      <p className="message-text">{reply}</p>
      <dl className="metrics">
        {fields.map(([label, testId, value]) => (
          <div key={testId}><dt>{label}</dt><dd data-testid={testId}>{value}</dd></div>
        ))}
      </dl>
    </article>
  );
}

function App() {
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const input = useRef(null);
  const transcript = useRef(null);

  useEffect(() => {
    const log = transcript.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [loading, turns, error]);

  async function submit(event) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || loading) return;
    setError("");
    setLoading(true);
    try {
      const { reply, metadata } = await sendMessage(sessionId, message, turns.length === 0 ? systemPrompt.trim() : "");
      setTurns(previous => [...previous, { message, reply, metadata }]);
      setDraft("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      input.current?.focus();
    }
  }

  function onKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form.requestSubmit();
    }
  }

  return (
    <div className="app">
      <header className="masthead">
        <div className="brand"><span className="brand-mark" aria-hidden="true">L</span>Lyftr<span className="brand-divider" />AI Chat</div>
        <span className="session">Session <code>{sessionId.slice(0, 8)}</code></span>
      </header>
      <main>
        <div className="conversation" ref={transcript}>
          {!turns.length && !loading && (
            <section className="welcome">
              <div className="chat-art" aria-hidden="true"><i /><b><span /><span /></b></div>
              <h1>Start a conversation</h1>
              <p>A new chat starts each time you reload this page.</p>
            </section>
          )}
          <div className="thread" role="log" aria-label="Conversation" aria-live="polite">
            {turns.map(({ message, reply, metadata }, index) => (
              <div className="turn" key={index}>
                <div className="user-message" aria-label="Your message">{message}</div>
                <AssistantReply reply={reply} metadata={metadata} />
              </div>
            ))}
            {loading && <div className="turn"><div className="user-message">{draft.trim()}</div><p role="status">Waiting for Lyftr…</p></div>}
          </div>
        </div>
        <div className="controls">
          {error && <p className="error" role="alert">{error}</p>}
          <details className="prompt">
            <summary>System prompt</summary>
            <label htmlFor="prompt">Instructions for this chat</label>
            <textarea id="prompt" data-testid="system-prompt-input" rows="2" value={systemPrompt}
              placeholder="For example, keep answers concise." disabled={loading || turns.length > 0}
              onChange={e => setSystemPrompt(e.target.value)} />
            <small>Set before your first message.</small>
          </details>
          <form onSubmit={submit}>
            <textarea aria-label="Message" ref={input} data-testid="chat-input" rows="2"
              placeholder="Message Lyftr…" value={draft} readOnly={loading}
              onChange={e => { setDraft(e.target.value); setError(""); }} onKeyDown={onKeyDown} />
            <div className="composer-actions">
              <span className="keyboard-hint"><kbd>↵</kbd> Send <span>·</span> Shift + Enter for a new line</span>
              <button data-testid="send-button" type="submit" disabled={!draft.trim() || loading}>
                {loading ? "Sending…" : "Send"} <span aria-hidden="true">↑</span>
              </button>
            </div>
          </form>
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
