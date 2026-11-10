const CONFIG = {
  student: {
    badge: "STUDENT PORTAL",
    sub: "Continue learning, track your academic progress, and get help from your AI learning assistant.",
    cards: [
      { icon: "◈", title: "My Learning", text: "Access your courses and learning materials.", go: "learning" },
      { icon: "✓", title: "My Progress", text: "Review your marks, attendance, and progress.", go: "progress" },
      { icon: "✦", title: "Study Assistant", text: "Ask questions and get personalized learning help.", go: "chat" },
    ],
  },
  instructor: {
    badge: "INSTRUCTOR PORTAL",
    sub: "Manage your class, review student performance, and use AI to support your teaching.",
    cards: [
      { icon: "◇", title: "My Class", text: "View students assigned to your class.", go: "class" },
      { icon: "↗", title: "Class Performance", text: "Review marks, attendance, and class progress.", go: "performance" },
      { icon: "✦", title: "Teaching Assistant", text: "Use AI to support lessons and student queries.", go: "chat" },
    ],
  },
  admin: {
    badge: "ADMINISTRATION PORTAL",
    sub: "Monitor LMS activity, academic performance, and institutional insights.",
    cards: [
      { icon: "▦", title: "LMS Overview", text: "Review students, instructors, and courses.", go: "overview" },
      { icon: "↗", title: "Performance", text: "Monitor academic and instructor-linked outcomes.", go: "performance" },
      { icon: "✦", title: "AI Insights", text: "Ask the assistant for LMS summaries and insights.", go: "chat" },
    ],
  },
};

export default function Dashboard({ user, navigate, openChat, online }) {
  const cfg = CONFIG[user.role];
  const go = (target) => (target === "chat" ? openChat() : navigate(target));
  return (
    <main className="page">
      <div className="container">
        <span className="badge">{cfg.badge}</span>
        <h1 className="page-title">Welcome back, {user.name}</h1>
        <p className="page-sub">{cfg.sub}</p>

        <div className="card-grid">
          {cfg.cards.map((c) => (
            <div className="feature-card" key={c.title}>
              <div className="feature-icon" aria-hidden>{c.icon}</div>
              <h2 className="feature-title">{c.title}</h2>
              <p className="feature-text">{c.text}</p>
              <button className="feature-link" onClick={() => go(c.go)}>Explore →</button>
            </div>
          ))}
        </div>

        <section className="ai-banner">
          <div className="ai-banner-icon" aria-hidden>✦</div>
          <div>
            <div className="ai-banner-kicker">EDULAYNE AI</div>
            <div className="ai-banner-title">Your AI assistant is ready</div>
            <div className="ai-banner-text">Get instant help using your authorized LMS information and learning context.</div>
          </div>
          <span className="online-pill"><span className={`dot ${online ? "" : "off"}`} /> {online ? "Online" : "Offline"}</span>
        </section>
      </div>
    </main>
  );
}
