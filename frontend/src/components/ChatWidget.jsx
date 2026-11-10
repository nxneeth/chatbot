import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { Markdown } from "../lib/markdown.jsx";

const storeKey = (user) => `edulayne_chat_${user.user_id}`;

function loadMessages(user) {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storeKey(user)));
    if (Array.isArray(saved) && saved.length) return saved;
  } catch {
    /* ignore */
  }
  return [{ role: "assistant", content: `Hi ${user.name}! How can I help you today?`, greeting: true }];
}

export default function ChatWidget({ user, open, setOpen, online }) {
  const [messages, setMessages] = useState(() => loadMessages(user));
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bodyRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    try {
      sessionStorage.setItem(storeKey(user), JSON.stringify(messages.slice(-40)));
    } catch {
      /* ignore */
    }
  }, [messages, user]);

  useEffect(() => {
    if (open) {
      bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
      inputRef.current?.focus();
    }
  }, [messages, open, busy]);

  const history = () =>
    messages
      .filter((m) => !m.greeting && !m.error)
      .slice(-10)
      .map((m) => ({ role: m.role, content: m.content }));

  async function send(text) {
    const message = (text ?? input).trim();
    if (!message || busy) return;
    setInput("");
    const prior = history();
    setMessages((m) => [...m, { role: "user", content: message }]);
    setBusy(true);
    try {
      const res = await api("/chat", { method: "POST", body: { message, history: prior } });
      setMessages((m) => [...m, { role: "assistant", content: res.reply, action: res.pending_action || null }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: e.message, error: true }]);
    } finally {
      setBusy(false);
    }
  }

  async function decide(index, action, confirm) {
    setMessages((m) => m.map((x, i) => (i === index ? { ...x, actionState: confirm ? "running" : "cancelled" } : x)));
    try {
      const res = await api(`/chat/actions/${action.id}/${confirm ? "confirm" : "cancel"}`, { method: "POST" });
      setMessages((m) => [
        ...m.map((x, i) => (i === index ? { ...x, actionState: confirm ? "confirmed" : "cancelled" } : x)),
        { role: "assistant", content: res.reply },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m.map((x, i) => (i === index ? { ...x, actionState: null } : x)),
        { role: "assistant", content: e.message, error: true },
      ]);
    }
  }

  return (
    <>
      {open && (
        <section className="chat-panel" aria-label="Edulayne AI chat">
          <div className="chat-head">
            <div className="chat-head-icon">✦</div>
            <div>
              <div className="chat-head-title">Edulayne AI</div>
              <div className="chat-head-status">
                <span className={`dot ${online ? "" : "off"}`} /> {online ? "Online" : "Offline"}
              </div>
            </div>
            <button className="chat-close" aria-label="Close chat" onClick={() => setOpen(false)}>×</button>
          </div>
          <div className="chat-body" ref={bodyRef}>
            {messages.map((m, i) => (
              <div key={i} className={`msg ${m.role === "user" ? "user" : "bot"}`}>
                {m.role !== "user" && <div className="msg-avatar">✦</div>}
                <div className="bubble">
                  {m.role === "user" ? m.content : <Markdown text={m.content} />}
                  {m.action && !m.actionState && (
                    <div className="action-card">
                      <button className={`btn ${m.action.destructive ? "danger" : ""}`} onClick={() => decide(i, m.action, true)}>
                        {m.action.destructive ? "Delete" : "Confirm"}
                      </button>
                      <button className="btn ghost" onClick={() => decide(i, m.action, false)}>Cancel</button>
                    </div>
                  )}
                  {m.action && m.actionState && (
                    <div className="action-state">
                      {m.actionState === "running" ? "Applying…" : m.actionState === "confirmed" ? "✓ Confirmed" : "Cancelled"}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {busy && (
              <div className="msg bot">
                <div className="msg-avatar">✦</div>
                <div className="bubble"><span className="typing"><span /><span /><span /></span></div>
              </div>
            )}
          </div>
          <form className="chat-foot" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <input
              ref={inputRef}
              className="chat-input"
              placeholder="Ask Edulayne AI..."
              value={input}
              maxLength={2000}
              onChange={(e) => setInput(e.target.value)}
            />
            <button className="chat-send" type="submit" disabled={!input.trim() || busy} aria-label="Send">↑</button>
          </form>
        </section>
      )}
      <button className="chat-fab" aria-label={open ? "Close chat" : "Open chat"} onClick={() => setOpen(!open)}>
        {open ? "×" : "✦"}
      </button>
    </>
  );
}
