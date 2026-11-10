import { useState } from "react";
import { api } from "../lib/api.js";
import Modal from "./Modal.jsx";

// Shown after signing in with a temporary password set by the admin.
export default function ChangePassword({ onDone, onLater }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (next.length < 6) return setError("New password must be at least 6 characters.");
    if (next !== again) return setError("The new passwords don't match.");
    setBusy(true);
    setError("");
    try {
      await api("/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } });
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Choose a new password" onClose={onLater}>
      <p className="muted" style={{ marginTop: 10 }}>You signed in with a temporary password. Please set your own.</p>
      <form onSubmit={submit}>
        <label className="field"><span className="field-label">Temporary password</span>
          <input className="input" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" /></label>
        <label className="field"><span className="field-label">New password</span>
          <input className="input" type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" /></label>
        <label className="field"><span className="field-label">Repeat new password</span>
          <input className="input" type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" /></label>
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onLater}>Later</button>
          <button type="submit" className="btn" disabled={busy}>{busy ? "Saving…" : "Save password"}</button>
        </div>
      </form>
    </Modal>
  );
}
