const SESSION_KEY = "edulayne_session";

export function loadSession() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY)) || null;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  try {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable: session lives in memory only */
  }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

export async function api(path, { method = "GET", body } = {}) {
  const session = loadSession();
  const headers = { "Content-Type": "application/json" };
  if (session?.token) headers.Authorization = `Bearer ${session.token}`;
  let res;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new Error("Can't reach the EduLayne server. Is the backend running?");
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }
  if (res.status === 401 && path !== "/auth/login") {
    onUnauthorized();
  }
  if (!res.ok) {
    const detail = data?.detail;
    const message = Array.isArray(detail) ? detail.map((d) => d.msg).join(", ") : detail || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

export const ROLE_LABEL = { student: "Student", instructor: "Instructor", admin: "Admin" };

export function fmt(n, suffix = "") {
  if (n === null || n === undefined) return "—";
  const v = Number.isInteger(n) ? n : Math.round(n * 10) / 10;
  return `${v}${suffix}`;
}
