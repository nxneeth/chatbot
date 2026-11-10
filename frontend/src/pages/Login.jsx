import { useState } from "react";
import { api } from "../lib/api.js";

export default function Login({ onLogin }) {
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!userId.trim() || !password) {
      setError("Enter your user ID and password.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await api("/auth/login", { method: "POST", body: { user_id: userId.trim(), password } });
      onLogin(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <section className="login-hero">
          <div className="hero-logo">E</div>
          <div className="hero-body">
            <div className="hero-kicker">AI-POWERED LEARNING</div>
            <h2 className="hero-title">Welcome to<span>Edulayne</span></h2>
            <p className="hero-text">Your intelligent learning environment for students, instructors, and administrators.</p>
          </div>
          <div className="hero-chips">
            <span className="hero-chip">Student</span>
            <span className="hero-chip">Instructor</span>
            <span className="hero-chip">Admin</span>
          </div>
        </section>
        <section className="login-form-wrap">
          <form className="login-form" onSubmit={submit} noValidate>
            <div className="kicker">WELCOME BACK</div>
            <h1>Sign in to your account</h1>
            <p className="sub">Enter your LMS credentials to continue.</p>
            <label className="field">
              <span className="field-label">User ID</span>
              <input className="input" placeholder="e.g. STD001" value={userId} autoComplete="username"
                onChange={(e) => setUserId(e.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">Password</span>
              <input className="input" type="password" placeholder="Enter your password" value={password}
                autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} />
            </label>
            {error && <div className="form-error">{error}</div>}
            <button className="btn-primary" type="submit" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"} <span aria-hidden>→</span>
            </button>
            <div className="login-foot">Secure access for registered LMS users</div>
          </form>
        </section>
      </div>
    </div>
  );
}
