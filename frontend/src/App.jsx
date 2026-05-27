import { useCallback, useEffect, useRef, useState } from "react";
import { marked } from "marked";
import {
  apiFetch,
  deleteHistoryItem,
  ensureGuestId,
  fetchChatSession,
  fetchHistory,
  fetchUsage,
  getUser,
  saveChatSession,
  signOut,
} from "./api";
import AuthModal from "./AuthModal";

marked.setOptions({ breaks: true, gfm: true });

function renderMarkdown(text) {
  return { __html: marked.parse(text || "") };
}

function TabIcon({ id }) {
  const props = {
    width: 20,
    height: 20,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round",
    strokeLinejoin: "round",
  };
  if (id === "chat") {
    return (
      <svg {...props}>
        <path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    );
  }
  if (id === "summary") {
    return (
      <svg {...props}>
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" />
      </svg>
    );
  }
  return null;
}

const TABS = [
  { id: "chat", label: "Chat", desc: "Ask with citations" },
  { id: "summary", label: "Summary", desc: "Full document summary" },
];

const HISTORY_KINDS = [
  { id: "all", label: "All activity" },
  { id: "search", label: "Search" },
  { id: "chat", label: "Chat threads" },
  { id: "upload", label: "Uploads" },
];

const KIND_LABELS = {
  search: "Search",
  chat: "Chat",
  extract: "Extract",
  upload: "Upload",
};

function formatHistoryTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

export default function App() {
  const [user, setUser] = useState(getUser());
  const [usage, setUsage] = useState(null);
  const [authModal, setAuthModal] = useState(null);
  const [activeTab, setActiveTab] = useState("chat");
  const [documents, setDocuments] = useState([]);
  const [activeDocId, setActiveDocId] = useState("");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [uploadStatus, setUploadStatus] = useState("");
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [summaryResult, setSummaryResult] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState("");
  const [historyKind, setHistoryKind] = useState("all");
  const [historyItems, setHistoryItems] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const fileRef = useRef(null);
  const chatRef = useRef(null);
  const chatSaveTimer = useRef(null);

  const refreshUsage = useCallback(async () => {
    try {
      await ensureGuestId();
      const u = await fetchUsage();
      setUsage(u);
      if (u.user) setUser(u.user);
    } catch {
      /* ignore */
    }
  }, []);

  const clearPrivateData = useCallback(() => {
    setDocuments([]);
    setHistoryItems([]);
    setActiveDocId("");
    setMessages([]);
    setSummaryResult(null);
    setSummaryError("");
    setUploadStatus("");
    setUploadSuccess(false);
  }, []);

  const loadDocuments = useCallback(async () => {
    if (!getUser()) {
      setDocuments([]);
      return;
    }
    try {
      const data = await apiFetch("/list_documents");
      const docs = data.documents || [];
      setDocuments(docs);
      setActiveDocId((current) => {
        if (current && docs.some((d) => d.doc_id === current)) return current;
        return docs[0]?.doc_id || "";
      });
    } catch {
      setDocuments([]);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    if (!getUser()) {
      setHistoryItems([]);
      return;
    }
    setHistoryLoading(true);
    try {
      const data = await fetchHistory(historyKind);
      setHistoryItems(data.items || []);
    } catch (err) {
      setHistoryItems([]);
      console.warn("History load failed:", err.message);
    } finally {
      setHistoryLoading(false);
    }
  }, [historyKind]);

  const docFilename = (docId) =>
    documents.find((d) => d.doc_id === docId)?.filename || docId;

  const persistChat = useCallback(
    (docId, msgs) => {
      if (!getUser() || !docId || !msgs?.length) return;
      if (chatSaveTimer.current) clearTimeout(chatSaveTimer.current);
      chatSaveTimer.current = setTimeout(() => {
        saveChatSession(docId, docFilename(docId), msgs).catch(() => {});
      }, 600);
    },
    [documents]
  );

  useEffect(() => {
    refreshUsage();
  }, [refreshUsage]);

  useEffect(() => {
    if (!user) {
      clearPrivateData();
      return;
    }
    loadDocuments();
    loadHistory();
  }, [user, historyKind, clearPrivateData, loadDocuments, loadHistory]);

  useEffect(() => {
    if (!user || !activeDocId) {
      if (!activeDocId) setMessages([]);
      return;
    }
    let cancelled = false;
    setMessages([]);
    (async () => {
      try {
        const session = await fetchChatSession(activeDocId);
        if (!cancelled) {
          setMessages(session.messages?.length ? session.messages : []);
        }
      } catch {
        if (!cancelled) setMessages([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, activeDocId]);

  useEffect(() => {
    if (user) persistChat(activeDocId, messages);
  }, [user, messages, activeDocId, persistChat]);

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages]);

  const openAuth = (mode) => setAuthModal(mode);

  const handleLimitError = (err) => {
    if (err.signUpRequired || err.code === "GUEST_LIMIT") {
      setAuthModal("signup");
    }
    return err.message;
  };

  const uploadFile = async (file) => {
    if (!file?.name?.toLowerCase().endsWith(".pdf")) {
      setUploadSuccess(false);
      setUploadStatus("Please upload a PDF file.");
      return;
    }
    setUploadSuccess(false);
    setUploadStatus("Uploading…");
    const form = new FormData();
    form.append("file", file);
    try {
      const data = await apiFetch("/upload", { method: "POST", body: form });
      setUploadSuccess(true);
      setUploadStatus("");
      setActiveDocId(data.doc_id);
      await refreshUsage();
      setMessages([
        {
          role: "system",
          text: `Document ready — **${data.filename}** is indexed.`,
        },
      ]);
      setActiveTab("chat");
      if (getUser()) {
        await loadDocuments();
        loadHistory();
      }
    } catch (err) {
      setUploadSuccess(false);
      setUploadStatus(handleLimitError(err));
    }
  };

  const handleUpload = () => {
    const file = fileRef.current?.files?.[0];
    if (file) uploadFile(file);
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) uploadFile(file);
  };

  const handleSummary = async () => {
    if (!activeDocId) return;
    setSummaryLoading(true);
    setSummaryError("");
    setSummaryResult(null);
    try {
      const data = await apiFetch("/summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_id: activeDocId }),
      });
      setSummaryResult(data.answer);
      await refreshUsage();
      if (getUser()) loadHistory();
    } catch (err) {
      setSummaryError(handleLimitError(err));
      if (err.signUpRequired) setAuthModal("signup");
    } finally {
      setSummaryLoading(false);
    }
  };

  const handleAsk = async (e) => {
    e.preventDefault();
    const question = input.trim();
    if (!question || !activeDocId) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: question }]);
    setLoading(true);
    try {
      const data = await apiFetch("/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, doc_id: activeDocId }),
      });
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: data.answer,
          chunks: data.retrieved_chunks || [],
          relevancy_score: data.relevancy_score,
        },
      ]);
      await refreshUsage();
      if (getUser()) loadHistory();
    } catch (err) {
      setMessages((m) => [...m, { role: "error", text: handleLimitError(err) }]);
    } finally {
      setLoading(false);
    }
  };

  const applyHistoryItem = (item) => {
    if (item.doc_id) setActiveDocId(item.doc_id);
    const p = item.payload || {};

    if (item.kind === "search") {
      setActiveTab("chat");
      setMessages([
        { role: "user", text: p.question },
        {
          role: "assistant",
          text: p.answer,
          relevancy_score: p.relevancy_score,
        },
      ]);
      return;
    }

    if (item.kind === "chat" && p.messages?.length) {
      setActiveTab("chat");
      setMessages(p.messages);
      return;
    }

    if (item.kind === "extract") {
      setActiveTab("summary");
      setSummaryResult(null);
      setSummaryError(
        "Structured extraction was removed. Use Summary or Chat for this document."
      );
      return;
    }

    if (item.kind === "search" && p.question?.toLowerCase().includes("summary")) {
      setActiveTab("summary");
      setSummaryResult(p.answer);
      return;
    }

    if (item.kind === "upload") {
      setActiveTab("chat");
      setMessages([
        {
          role: "system",
          text: `Opened upload history — **${p.filename || item.doc_id}** (${p.page_count || "?"} pages).`,
        },
      ]);
    }
  };

  const removeHistoryItem = async (e, item) => {
    e.stopPropagation();
    try {
      await deleteHistoryItem(item.id, item.kind);
      setHistoryItems((list) => list.filter((h) => h.id !== item.id));
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="app-shell">
      {authModal && (
        <AuthModal
          mode={authModal}
          onClose={() => setAuthModal(null)}
          onSuccess={(u) => {
            setUser(u);
            refreshUsage();
          }}
        />
      )}

      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">P</div>
          <div>
            <span className="brand-name">Paperpal AI</span>
            <span className="brand-tag">PDF Intelligence</span>
          </div>
        </div>
        <div className="topbar-actions">
          {user ? (
            <>
              <span className="user-pill">{user.name}</span>
              <button
                type="button"
                className="btn-outline"
                onClick={() => {
                  signOut(() => {
                    setUser(null);
                    clearPrivateData();
                    refreshUsage();
                  });
                }}
              >
                Sign out
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="btn-outline"
                onClick={() => openAuth("signin")}
              >
                Sign in
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={() => openAuth("signup")}
              >
                Sign up free
              </button>
            </>
          )}
        </div>
      </header>

      <div className="page-grid">
        <aside className="sidebar">
          <div className="sidebar-block">
            <p className="label">Live demo</p>
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`nav-item ${activeTab === t.id ? "active" : ""}`}
                onClick={() => setActiveTab(t.id)}
              >
                <span className="nav-icon">
                  <TabIcon id={t.id} />
                </span>
                <span className="nav-text">
                  <span className="nav-title">{t.label}</span>
                  <span className="nav-desc">{t.desc}</span>
                </span>
              </button>
            ))}
          </div>

          {user ? (
            <>
              <div className="sidebar-block">
                <p className="label">Documents</p>
                {documents.length === 0 ? (
                  <p className="hint">No PDFs yet — upload one in the demo</p>
                ) : (
                  <ul className="doc-list">
                    {documents.map((d) => (
                      <li key={d.doc_id}>
                        <button
                          type="button"
                          className={activeDocId === d.doc_id ? "doc active" : "doc"}
                          onClick={() => setActiveDocId(d.doc_id)}
                        >
                          <span className="doc-name">{d.filename}</span>
                          <span className="doc-meta">
                            {d.page_count} {d.page_count === 1 ? "page" : "pages"}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="sidebar-block history-block">
                <p className="label">History</p>
                <select
                  className="history-filter"
                  value={historyKind}
                  onChange={(e) => setHistoryKind(e.target.value)}
                  aria-label="History type"
                >
                  {HISTORY_KINDS.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.label}
                    </option>
                  ))}
                </select>
                {historyLoading ? (
                  <p className="hint">Loading…</p>
                ) : historyItems.length === 0 ? (
                  <p className="hint">No saved activity yet</p>
                ) : (
                  <ul className="history-list">
                    {historyItems.map((item) => (
                      <li key={`${item.kind}-${item.id}`}>
                        <button
                          type="button"
                          className="history-item"
                          onClick={() => applyHistoryItem(item)}
                          title="Restore this session"
                        >
                          <span className={`history-kind kind-${item.kind}`}>
                            {KIND_LABELS[item.kind] || item.kind}
                          </span>
                          <span className="history-title">{item.title}</span>
                          <span className="history-time">
                            {formatHistoryTime(item.created_at)}
                          </span>
                        </button>
                        <button
                          type="button"
                          className="history-delete"
                          aria-label="Delete"
                          onClick={(e) => removeHistoryItem(e, item)}
                        >
                          ×
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          ) : (
            <div className="sidebar-block">
              <p className="hint sign-in-hint">
                Sign in to save documents and activity history across sessions.
              </p>
            </div>
          )}

          {!user && usage && (
            <div className="usage-card">
              <p className="usage-title">Guest trial</p>
              <div className="usage-bar">
                <div
                  className="usage-fill"
                  style={{
                    width: `${((usage.operations_used || 0) / (usage.daily_limit || 2)) * 100}%`,
                  }}
                />
              </div>
              <p className="usage-text">
                {usage.remaining} of {usage.daily_limit} operations left today
              </p>
              <button
                type="button"
                className="btn-primary full"
                onClick={() => openAuth("signup")}
              >
                Unlock unlimited
              </button>
            </div>
          )}
        </aside>

        <main className="main">
          <section className="hero hero-centered">
            <h1 className="hero-title">
              <span className="hero-line">Turn any PDF into a</span>
              <span className="hero-line gradient-text">searchable knowledge base</span>
            </h1>
          </section>

          <div className="workspace-card">
            <div className="workspace-header">
              <h2>Try the demo</h2>
              <div className="tab-pills">
                {TABS.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={activeTab === t.id ? "pill active" : "pill"}
                    onClick={() => setActiveTab(t.id)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            {activeTab === "chat" && (
              <div className="workspace-body split">
                <div
                  className={`upload-panel ${dragOver ? "drag-over" : ""}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOver(true);
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={onDrop}
                >
                  <div className="upload-icon">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M12 16V4m0 0l-4 4m4-4l4 4M4 20h16"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                      />
                    </svg>
                  </div>
                  <h3>Upload your PDF</h3>
                  <p>Drag & drop or browse — max quality with OCR + vision</p>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".pdf"
                    hidden
                    id="pdf-input"
                    onChange={handleUpload}
                  />
                  <label htmlFor="pdf-input" className="btn-primary">
                    Choose file
                  </label>
                  {uploadSuccess ? (
                    <p className="upload-success" role="status">
                      <span className="upload-success-icon" aria-hidden="true">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                          <path
                            d="M20 6L9 17l-5-5"
                            stroke="currentColor"
                            strokeWidth="2.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </span>
                      File uploaded successfully
                    </p>
                  ) : (
                    uploadStatus && (
                      <p
                        className={`status-msg ${
                          uploadStatus === "Uploading…"
                            ? "status-msg--pending"
                            : "status-msg--error"
                        }`}
                      >
                        {uploadStatus}
                      </p>
                    )
                  )}
                </div>

                <div className="chat-panel">
                  <div className="chat-header">
                    <span>Conversation</span>
                    {activeDocId && (
                      <span className="active-doc">{activeDocId}</span>
                    )}
                  </div>
                  <div className="chat-messages" ref={chatRef}>
                    {messages.length === 0 && (
                      <div className="chat-welcome">
                        <p>Ask about content, figures, or projects in your PDF.</p>
                        <ul>
                          <li>&quot;Summarize chapter 4&quot;</li>
                          <li>&quot;What is the red segment in Fig 4.4.1?&quot;</li>
                          <li>&quot;List all projects with dates&quot;</li>
                        </ul>
                      </div>
                    )}
                    {messages.map((msg, i) => (
                      <div key={i} className={`message ${msg.role}`}>
                        {msg.role === "assistant" ? (
                          <div
                            className="answer-body"
                            dangerouslySetInnerHTML={renderMarkdown(msg.text)}
                          />
                        ) : (
                          <p>{msg.text}</p>
                        )}
                        {msg.chunks?.length > 0 && (
                          <div className="sources">
                            {msg.chunks.slice(0, 4).map((c) => (
                              <span key={c.chunk_id} className="source-tag">
                                p.{c.page} · {(c.score * 100).toFixed(0)}%
                              </span>
                            ))}
                          </div>
                        )}
                        {msg.relevancy_score != null && (
                          <span className="relevancy">
                            Relevancy {(msg.relevancy_score * 100).toFixed(0)}%
                          </span>
                        )}
                      </div>
                    ))}
                    {loading && (
                      <div className="loading-dots">
                        <span />
                        <span />
                        <span />
                      </div>
                    )}
                  </div>
                  <form onSubmit={handleAsk} className="chat-form">
                    <input
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      placeholder={
                        activeDocId
                          ? "Ask a question about your document…"
                          : "Upload a PDF to start"
                      }
                      disabled={!activeDocId || loading}
                    />
                    <button
                      type="submit"
                      className="btn-primary"
                      disabled={!activeDocId || loading}
                    >
                      Send
                    </button>
                  </form>
                </div>
              </div>
            )}

            {activeTab === "summary" && (
              <div
                className={`workspace-body centered wide summary-panel ${
                  summaryResult || summaryLoading || summaryError
                    ? "has-output"
                    : ""
                }`}
              >
                <h3>Document summary</h3>
                <p className="summary-hint">
                  Analyzes every page (brief + full summary). Most PDFs finish in
                  about 15–40 seconds.
                </p>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={handleSummary}
                  disabled={!activeDocId || summaryLoading}
                >
                  {summaryLoading ? "Analyzing all pages…" : "Generate summary"}
                </button>
                {summaryError && (
                  <p className="summary-error">{summaryError}</p>
                )}
                {summaryResult && (
                  <div
                    className="summary-output answer-body"
                    dangerouslySetInnerHTML={renderMarkdown(summaryResult)}
                  />
                )}
              </div>
            )}
          </div>

          <footer className="footer">
            <p>
              <strong>Paperpal AI</strong> — PDF Q&amp;A with citations, summaries,
              and guest-friendly demos.
            </p>
          </footer>
        </main>
      </div>
    </div>
  );
}
