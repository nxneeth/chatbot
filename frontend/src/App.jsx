import { useCallback, useEffect, useState } from "react";
import ChangePassword from "./components/ChangePassword.jsx";
import ChatWidget from "./components/ChatWidget.jsx";
import Header from "./components/Header.jsx";
import { api, loadSession, saveSession, setUnauthorizedHandler } from "./lib/api.js";
import { AdminOverview, AdminPerformance } from "./pages/AdminPages.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import { InstructorClass, InstructorPerformance } from "./pages/InstructorPages.jsx";
import Login from "./pages/Login.jsx";
import { StudentLearning, StudentProgress } from "./pages/StudentPages.jsx";

const PAGES = {
  student: { learning: StudentLearning, progress: StudentProgress },
  instructor: { class: InstructorClass, performance: InstructorPerformance },
  admin: { overview: AdminOverview, performance: AdminPerformance },
};

const currentRoute = () => window.location.hash.replace(/^#\/?/, "");

export default function App() {
  const [session, setSession] = useState(loadSession);
  const [route, setRoute] = useState(currentRoute);
  const [chatOpen, setChatOpen] = useState(false);
  const [online, setOnline] = useState(true);
  const [skipPw, setSkipPw] = useState(false);

  const signOut = useCallback(() => {
    saveSession(null);
    try {
      Object.keys(sessionStorage).filter((k) => k.startsWith("edulayne_chat_")).forEach((k) => sessionStorage.removeItem(k));
    } catch {
      /* ignore */
    }
    setSession(null);
    setChatOpen(false);
    window.location.hash = "";
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(signOut);
    const onHash = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [signOut]);

  useEffect(() => {
    if (!session) return;
    api("/health").then(() => setOnline(true)).catch(() => setOnline(false));
    api("/auth/me").catch(() => {}); // signs out automatically if the token expired
  }, [session]);

  if (!session) {
    return <Login onLogin={(s) => { saveSession(s); setSession(s); }} />;
  }

  const user = session.user;
  const navigate = (r) => { window.location.hash = r ? `/${r}` : "/"; };
  const Page = PAGES[user.role]?.[route];

  return (
    <>
      <Header user={user} onHome={() => navigate("")} onSignOut={signOut} />
      {Page ? (
        <Page onBack={() => navigate("")} openChat={() => setChatOpen(true)} />
      ) : (
        <Dashboard user={user} navigate={navigate} openChat={() => setChatOpen(true)} online={online} />
      )}
      {user.must_change_password && !skipPw && (
        <ChangePassword
          onLater={() => setSkipPw(true)}
          onDone={() => {
            const s = { ...session, user: { ...user, must_change_password: false } };
            saveSession(s);
            setSession(s);
          }}
        />
      )}
      <ChatWidget key={user.user_id} user={user} open={chatOpen} setOpen={setChatOpen} online={online} />
    </>
  );
}
