const API = "/api";
const TOKEN_KEY = "paperpal_token";
const USER_KEY = "paperpal_user";
const GUEST_KEY = "paperpal_guest_id";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser() {
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function setAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function signOut(onDone) {
  clearAuth();
  onDone?.();
}

export function getGuestId() {
  return localStorage.getItem(GUEST_KEY);
}

export function setGuestId(id) {
  localStorage.setItem(GUEST_KEY, id);
}

export async function ensureGuestId() {
  let id = getGuestId();
  if (!id) {
    const res = await fetch(`${API}/auth/guest`, { method: "POST" });
    const data = await res.json();
    id = data.guest_id;
    setGuestId(id);
  }
  return id;
}

export function authHeaders(extra = {}) {
  const headers = { ...extra };
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const guest = getGuestId();
  if (guest) {
    headers["X-Guest-Id"] = guest;
  }
  return headers;
}

export async function apiFetch(path, options = {}) {
  await ensureGuestId();
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: authHeaders(options.headers || {}),
  });
  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!res.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "object" ? detail.message : detail || res.statusText;
    const err = new Error(message || "Request failed");
    err.code = typeof detail === "object" ? detail.code : null;
    err.signUpRequired = typeof detail === "object" ? detail.sign_up_required : false;
    throw err;
  }
  return data;
}

export async function fetchUsage() {
  return apiFetch("/auth/usage");
}

export async function fetchHistory(kind = "all", limit = 40) {
  return apiFetch(`/history?kind=${encodeURIComponent(kind)}&limit=${limit}`);
}

export async function fetchChatSession(docId) {
  return apiFetch(`/history/chat/${encodeURIComponent(docId)}`);
}

export async function saveChatSession(docId, filename, messages) {
  return apiFetch("/history/chat", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      doc_id: docId,
      filename: filename || docId,
      messages,
    }),
  });
}

export async function deleteHistoryItem(id, kind = "search") {
  return apiFetch(`/history/${id}?kind=${encodeURIComponent(kind)}`, {
    method: "DELETE",
  });
}

export async function signUp(email, password, name) {
  await ensureGuestId();
  const res = await fetch(`${API}/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name }),
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(data.detail || "Sign up failed");
  return data;
}

export async function signIn(email, password) {
  const res = await fetch(`${API}/auth/signin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(data.detail || "Sign in failed");
  return data;
}

export { API };
