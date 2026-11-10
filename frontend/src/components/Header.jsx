import { ROLE_LABEL } from "../lib/api.js";

export default function Header({ user, onHome, onSignOut }) {
  return (
    <header className="app-header">
      <div className="app-header-inner">
        <a className="brand" href="#/" onClick={(e) => { e.preventDefault(); onHome(); }}>
          <div className="brand-logo">E</div>
          <div>
            <div className="brand-name">EduLayne</div>
            <div className="brand-sub">AI Learning Environment</div>
          </div>
        </a>
        <div className="user-box">
          <div className="user-meta">
            <div className="user-name">{user.name}</div>
            <div className="user-sub">{user.user_id} · {ROLE_LABEL[user.role]}</div>
          </div>
          <div className="avatar">{(user.name || "?").trim().charAt(0).toUpperCase()}</div>
          <button className="btn-outline" onClick={onSignOut}>Sign out</button>
        </div>
      </div>
    </header>
  );
}
