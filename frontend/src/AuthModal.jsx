import { useState } from "react";
import { setAuth, signIn, signUp } from "./api";

export default function AuthModal({ mode, onClose, onSuccess }) {
  const [tab, setTab] = useState(mode || "signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data =
        tab === "signup"
          ? await signUp(email, password, name)
          : await signIn(email, password);
      setAuth(data.token, data.user);
      onSuccess(data.user);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>
        <div className="modal-badge">Paperpal AI</div>
        <h2>{tab === "signup" ? "Create your account" : "Welcome back"}</h2>
        <p className="modal-sub">
          Unlimited PDF uploads and chats — built for production demos.
        </p>

        <div className="auth-tabs">
          <button
            type="button"
            className={tab === "signup" ? "active" : ""}
            onClick={() => setTab("signup")}
          >
            Sign up
          </button>
          <button
            type="button"
            className={tab === "signin" ? "active" : ""}
            onClick={() => setTab("signin")}
          >
            Sign in
          </button>
        </div>

        <form onSubmit={submit} className="auth-form">
          {tab === "signup" && (
            <input
              type="text"
              placeholder="Full name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          )}
          <input
            type="email"
            placeholder="Work or personal email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password (min 6 characters)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
          />
          {error && <p className="auth-error">{error}</p>}
          <button type="submit" className="btn-primary full" disabled={loading}>
            {loading ? "Please wait…" : tab === "signup" ? "Get started free" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
