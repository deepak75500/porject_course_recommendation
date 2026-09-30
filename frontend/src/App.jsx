import { useState, useEffect, createContext, useContext, useCallback } from "react";
import "./style.css";

/* ─── API Helper ─────────────────────────────────────────────────────────── */
const BASE = "/api";

function apiFetch(path, opts = {}) {
  const token = localStorage.getItem("token");
  const headers = { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...opts.headers };
  return fetch(`${BASE}${path}`, { ...opts, headers })
    .then(async (r) => {
      if (!r.ok) {
        if (r.status === 401) {
          localStorage.removeItem("token");
          localStorage.removeItem("user");
          localStorage.removeItem("coursefinder_history");
          sessionStorage.removeItem("coursefinder_plan_cache");
        }
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || r.statusText);
      }
      return r.json();
    });
}

const api = {
  get: (p) => apiFetch(p),
  post: (p, b) => apiFetch(p, { method: "POST", body: JSON.stringify(b) }),
  put: (p, b) => apiFetch(p, { method: "PUT", body: JSON.stringify(b) }),
  del: (p) => apiFetch(p, { method: "DELETE" }),
};

/* ─── Auth Context ───────────────────────────────────────────────────────── */
const AuthCtx = createContext(null);

function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem("user")); } catch { return null; }
  });
  const [toast, setToast] = useState([]);

  const addToast = useCallback((msg, type = "success") => {
    const id = Date.now();
    setToast((t) => [...t, { id, msg, type }]);
    setTimeout(() => setToast((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);

  const login = useCallback((token, userData) => {
    localStorage.setItem("token", token);
    localStorage.setItem("user", JSON.stringify(userData));
    setUser(userData);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    localStorage.removeItem("coursefinder_history");
    sessionStorage.removeItem("coursefinder_plan_cache");
    setUser(null);
    addToast("Logged out successfully", "info");
  }, [addToast]);

  return (
    <AuthCtx.Provider value={{ user, login, logout, addToast }}>
      {children}
      <div className="toast-container">
        {toast.map((t) => (
          <div key={t.id} className={`toast alert-${t.type}`}>{t.msg}</div>
        ))}
      </div>
    </AuthCtx.Provider>
  );
}

const useAuth = () => useContext(AuthCtx);

/* ─── Router (hash-based, no deps) ──────────────────────────────────────── */
function useRoute() {
  const [route, setRoute] = useState(window.location.hash.slice(1) || "/");
  useEffect(() => {
    const handler = () => setRoute(window.location.hash.slice(1) || "/");
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  const navigate = (r) => { window.location.hash = r; };
  return { route, navigate };
}

/* ─── Navbar ─────────────────────────────────────────────────────────────── */
function Navbar({ route, navigate }) {
  const { user, logout } = useAuth();

  return (
    <nav className="navbar">
      <div className="container">
        <a className="nav-logo" onClick={() => navigate("/")} style={{ cursor: "pointer" }}>
          <div className="nav-logo-icon">🎓</div>
          CourseAI
        </a>

        <div className="nav-links">
          <button className={`nav-link ${route === "/" ? "active" : ""}`} onClick={() => navigate("/")}>
            🔍 Find Courses
          </button>

          {user && (
            <button className={`nav-link ${route === "/dashboard" ? "active" : ""}`} onClick={() => navigate("/dashboard")}>
              📊 Dashboard
            </button>
          )}

          {user?.role === "admin" && (
            <button className={`nav-link ${route.startsWith("/admin") ? "active" : ""}`} onClick={() => navigate("/admin")}>
              ⚡ Admin
            </button>
          )}

          {user ? (
            <>
              <div className="nav-badge">
                <div className="nav-avatar">{(user.username || "U")[0].toUpperCase()}</div>
                <span>{user.username}</span>
                {user.role === "admin" && <span className="badge badge-admin">Admin</span>}
              </div>
              <button className="btn btn-ghost btn-sm" onClick={logout}>Logout</button>
            </>
          ) : (
            <>
              <button className="btn btn-ghost btn-sm" onClick={() => navigate("/login")}>Login</button>
              <button className="btn btn-primary btn-sm" onClick={() => navigate("/register")}>Sign Up</button>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}

/* ─── Login Page ─────────────────────────────────────────────────────────── */
function LoginPage({ navigate }) {
  const { login, addToast } = useAuth();
  const [form, setForm] = useState({ email_or_username: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErr(""); setLoading(true);
    try {
      const r = await api.post("/auth/login", form);
      login(r.access_token, r.user);
      addToast(`Welcome back, ${r.user.username}! 👋`);
      navigate(r.user.role === "admin" ? "/admin" : "/");
    } catch (e) { setErr(e.message); }
    setLoading(false);
  };

  return (
    <div className="auth-page">
      <div className="glass auth-card">
        <div className="auth-header">
          <div className="logo-mark">🎓</div>
          <h1 className="auth-title">Welcome back</h1>
          <p className="auth-sub">Sign in to your CourseAI account</p>
        </div>

        {err && <div className="alert alert-error">⚠️ {err}</div>}

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Email or Username</label>
            <input
              id="login-identifier"
              className="form-input"
              type="text"
              placeholder="you@example.com"
              value={form.email_or_username}
              onChange={(e) => setForm({ ...form, email_or_username: e.target.value })}
              required
            />
          </div>
          <div className="form-group">
            <label className="form-label">Password</label>
            <input
              id="login-password"
              className="form-input"
              type="password"
              placeholder="••••••••"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              required
            />
          </div>
          <button id="login-submit" className="btn btn-primary w-full" type="submit" disabled={loading}>
            {loading ? <><div className="spinner" /> Signing in…</> : "Sign In →"}
          </button>
        </form>

        <div className="auth-divider">or</div>

        <div className="alert alert-info" style={{ fontSize: 13 }}>
          🔑 Demo Admin: <strong>admin@coursefinder.ai</strong> / <strong>admin123</strong>
        </div>

        <p className="auth-switch">
          Don't have an account?{" "}
          <a onClick={() => navigate("/register")} style={{ cursor: "pointer" }}>Create one →</a>
        </p>
      </div>
    </div>
  );
}

/* ─── Register Page ──────────────────────────────────────────────────────── */
function RegisterPage({ navigate }) {
  const { login, addToast } = useAuth();
  const [form, setForm] = useState({ email: "", username: "", password: "", full_name: "" });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErr(""); setLoading(true);
    try {
      const r = await api.post("/auth/register", form);
      login(r.access_token, r.user);
      addToast("Account created! Welcome to CourseAI 🎉");
      navigate("/");
    } catch (e) { setErr(e.message); }
    setLoading(false);
  };

  const F = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) });

  return (
    <div className="auth-page">
      <div className="glass auth-card">
        <div className="auth-header">
          <div className="logo-mark">✨</div>
          <h1 className="auth-title">Create account</h1>
          <p className="auth-sub">Start your AI-powered learning journey</p>
        </div>

        {err && <div className="alert alert-error">⚠️ {err}</div>}

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Full Name</label>
            <input id="reg-name" className="form-input" placeholder="Jane Smith" {...F("full_name")} />
          </div>
          <div className="form-group">
            <label className="form-label">Email *</label>
            <input id="reg-email" className="form-input" type="email" placeholder="jane@example.com" required {...F("email")} />
          </div>
          <div className="form-group">
            <label className="form-label">Username *</label>
            <input id="reg-username" className="form-input" placeholder="jane_smith" required {...F("username")} />
          </div>
          <div className="form-group">
            <label className="form-label">Password * <span className="text-muted text-sm">(min 6 chars)</span></label>
            <input id="reg-password" className="form-input" type="password" placeholder="••••••••" required {...F("password")} />
          </div>
          <button id="reg-submit" className="btn btn-primary w-full" type="submit" disabled={loading}>
            {loading ? <><div className="spinner" /> Creating account…</> : "Create Account →"}
          </button>
        </form>

        <p className="auth-switch">
          Already have an account?{" "}
          <a onClick={() => navigate("/login")} style={{ cursor: "pointer" }}>Sign in →</a>
        </p>
      </div>
    </div>
  );
}

/* ─── Course Card ────────────────────────────────────────────────────────── */
/* ─── Course Card ────────────────────────────────────────────────────────── */
function CourseCard({ c, query, onBookmark, bookmarked, onEnroll, isEnrolled }) {
  const { user, addToast } = useAuth();
  const [vote, setVote] = useState(null);

  const sendVote = (helpful) => {
    setVote(helpful);
    api.post("/feedback", { course_id: c.course_id, query, helpful }).catch(() => {});
  };

  const handleEnroll = async () => {
    if (!user) { addToast("Please login to enroll", "error"); return; }
    if (onEnroll) {
      await onEnroll(c.course_id, c.title);
    } else {
      try {
        await api.post("/user/enroll", { course_id: c.course_id });
        addToast(`Enrolled in "${c.title}" ✅`);
      } catch (e) { addToast(e.message, "error"); }
    }
  };

  const diffClass = `diff-${(c.difficulty || "").toLowerCase().replace(/\s+/, "")}`;

  return (
    <div className="course-card glass">
      <div className="course-card-head">
        <h4 className="course-title">
          {c.url ? <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a> : c.title}
        </h4>
        <span className={`diff-badge ${diffClass}`}>{c.difficulty}</span>
      </div>

      <div className="course-meta">
        <span>{c.organization}</span>
        <span className="meta-dot">·</span>
        <span>{c.category}</span>
        {c.duration && <><span className="meta-dot">·</span><span>⏱ {c.duration}</span></>}
        {c.rating && <><span className="meta-dot">·</span><span className="rating-star">★</span><span>{c.rating}</span></>}
      </div>

      <p className="course-desc">{c.reason || c.why || c.blurb}</p>

      {c.prerequisites?.length > 0 && (
        <div className="text-sm text-muted">
          Prerequisites: {c.prerequisites.map((p) => p.title).join(", ")}
        </div>
      )}

      {c.skills?.length > 0 && (
        <div className="skills-row">
          {c.skills.slice(0, 5).map((s) => <span key={s} className="skill-tag">{s}</span>)}
          {c.skills.length > 5 && <span className="skill-tag">+{c.skills.length - 5}</span>}
        </div>
      )}

      <div className="vote-row">
        <button className={`vote-btn helpful ${vote === true ? "on" : ""}`} onClick={() => sendVote(true)}>👍 Helpful</button>
        <button className={`vote-btn notrelevant ${vote === false ? "on" : ""}`} onClick={() => sendVote(false)}>👎 Not relevant</button>
        <button
          className={`vote-btn ${isEnrolled ? "helpful on" : ""}`}
          style={{ marginLeft: 8 }}
          onClick={handleEnroll}
          disabled={isEnrolled}
        >
          {isEnrolled ? "✅ Enrolled" : "Enroll"}
        </button>
        {user && (
          <button
            className={`bookmark-btn ${bookmarked ? "active" : ""}`}
            onClick={() => onBookmark && onBookmark(c.course_id)}
            title={bookmarked ? "Remove bookmark" : "Bookmark"}
          >
            {bookmarked ? "★" : "☆"}
          </button>
        )}
      </div>
    </div>
  );
}

/* ─── Main Finder Page ───────────────────────────────────────────────────── */
const EXAMPLES = [
  "I want to learn data science from scratch. What path should I follow?",
  "I know Python and SQL. What's next for machine learning?",
  "I want to build a career in cloud computing. What courses do I need?",
  "Can you suggest a path from beginner to advanced data analytics?",
];

function FinderPage() {
  const { user, addToast } = useAuth();
  const [meta, setMeta] = useState(null);
  const [goal, setGoal] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [bookmarks, setBookmarks] = useState(new Set());
  const [enrolledSet, setEnrolledSet] = useState(new Set());
  const [history, setHistory] = useState(() => {
    try { return JSON.parse(localStorage.getItem("coursefinder_history") || "[]"); } catch { return []; }
  });
  const [resultCache, setResultCache] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem("coursefinder_plan_cache") || "{}"); } catch { return {}; }
  });
  const [filters, setFilters] = useState({ difficulty: "", category: "", max_weeks: "", min_rating: "" });

  const loadUserData = useCallback(() => {
    if (user) {
      api.get("/user/bookmarks")
        .then((r) => setBookmarks(new Set((r.bookmarks || []).map((b) => b.course_id))))
        .catch(() => {});
      api.get("/user/enrollments")
        .then((r) => setEnrolledSet(new Set((r.enrollments || []).map((e) => e.course_id))))
        .catch(() => {});
      api.get("/user/history")
        .then((r) => {
          if (r.history && r.history.length > 0) {
            const queries = r.history.map((h) => h.query);
            setHistory(queries);
            localStorage.setItem("coursefinder_history", JSON.stringify(queries));
          }
        })
        .catch(() => {});
    } else {
      setBookmarks(new Set());
      setEnrolledSet(new Set());
      setHistory([]);
      setRes(null);
    }
  }, [user]);

  useEffect(() => {
    api.get("/meta").then(setMeta).catch(() => setErr("Backend not reachable on :8000"));
    loadUserData();
  }, [user, loadUserData]);

  const run = async (g = goal) => {
    if (!user) { setErr("Please sign in to use the AI course finder."); return; }
    const q = (g || goal).trim();
    if (!q) return;

    // Update history locally
    setHistory((prev) => {
      const next = [q, ...prev.filter((x) => x.toLowerCase() !== q.toLowerCase())].slice(0, 8);
      localStorage.setItem("coursefinder_history", JSON.stringify(next));
      return next;
    });

    const cacheKey = `${q.toLowerCase()}__${filters.difficulty || ""}__${filters.category || ""}__${filters.max_weeks || ""}__${filters.min_rating || ""}`;
    if (resultCache[cacheKey]) {
      setRes({ ...resultCache[cacheKey], goal: q });
      setBusy(false);
      loadUserData();
      return;
    }

    setBusy(true); setErr("");
    try {
      const body = {
        goal: q,
        filters: {
          difficulty: filters.difficulty ? [filters.difficulty] : null,
          category: filters.category ? [filters.category] : null,
          max_weeks: filters.max_weeks ? parseFloat(filters.max_weeks) : null,
          min_rating: filters.min_rating ? parseFloat(filters.min_rating) : null,
        },
      };
      const data = await api.post("/plan", body);
      const fullRes = { ...data, goal: q };
      setRes(fullRes);
      setResultCache((prev) => {
        const next = { ...prev, [cacheKey]: fullRes };
        try { sessionStorage.setItem("coursefinder_plan_cache", JSON.stringify(next)); } catch {}
        return next;
      });
      // Refresh enrollments & bookmarks
      loadUserData();
    } catch (e) { setErr(String(e.message)); }
    setBusy(false);
  };

  const handleEnroll = async (courseId, title) => {
    if (!user) { addToast("Please login to enroll", "error"); return; }
    try {
      await api.post("/user/enroll", { course_id: courseId });
      setEnrolledSet((prev) => new Set([...prev, courseId]));
      addToast(`Enrolled in "${title}" ✅`);
    } catch (e) { addToast(e.message, "error"); }
  };

  const toggleBookmark = async (courseId) => {
    if (!user) { addToast("Please login to bookmark courses", "error"); return; }
    const isBookmarked = bookmarks.has(courseId);
    try {
      await api.post("/user/bookmark", { course_id: courseId, action: isBookmarked ? "remove" : "add" });
      setBookmarks((prev) => {
        const next = new Set(prev);
        isBookmarked ? next.delete(courseId) : next.add(courseId);
        return next;
      });
      addToast(isBookmarked ? "Bookmark removed" : "Course bookmarked ★", isBookmarked ? "info" : "success");
    } catch (e) { addToast(e.message, "error"); }
  };

  const clearHistory = async () => {
    setHistory([]);
    localStorage.removeItem("coursefinder_history");
    if (user) {
      await api.del("/user/history").catch(() => {});
    }
    addToast("Search history cleared", "info");
  };

  return (
    <div>
      {/* Hero */}
      <div className="hero">
        <div className="container">
          <div className="hero-badge">
            <span>🤖</span>
            <span>AI-Powered Learning Pathfinder</span>
          </div>
          <h1 className="hero-title">
            Find Your Perfect<br />
            <span className="gradient-text">Learning Path</span>
          </h1>
          <p className="hero-sub">
            Describe your goals and background. Our AI analyzes thousands of courses
            and builds a personalized roadmap just for you.
          </p>

          {meta && (
            <div className="hero-stats">
              <div className="hero-stat"><strong>{meta.courses.toLocaleString()}</strong><span>Courses</span></div>
              <div className="hero-stat"><strong>{meta.categories?.length}</strong><span>Categories</span></div>
              <div className="hero-stat"><strong>{meta.dense ? "Semantic" : "Keyword"}</strong><span>Search</span></div>
              <div className="hero-stat"><strong>{meta.llm ? "On" : "Rule-based"}</strong><span>AI Mode</span></div>
            </div>
          )}
        </div>
      </div>

      {/* Search Box */}
      <div className="container">
        <div className="search-box">
          {!user ? (
            /* ── Auth Gate Wall ── */
            <div className="glass" style={{ padding: "var(--sp-xl)", textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: "var(--sp-lg)" }}>
              <div style={{ fontSize: 52, lineHeight: 1 }}>🔒</div>
              <div>
                <h3 style={{ marginBottom: 8 }}>Sign in to Unlock AI Course Finder</h3>
                <p style={{ maxWidth: 420, margin: "0 auto", fontSize: 15 }}>
                  Create a free account or sign in to get your personalized AI-powered learning path, bookmark courses, and track your progress.
                </p>
              </div>

              <div style={{ width: "100%", position: "relative", pointerEvents: "none", userSelect: "none" }}>
                <div style={{ filter: "blur(4px)", opacity: 0.4, border: "1px solid var(--clr-border)", borderRadius: "var(--r-lg)", padding: "var(--sp-md)" }}>
                  <div style={{ background: "rgba(255,255,255,0.05)", borderRadius: "var(--r-md)", padding: "12px 14px", color: "var(--clr-subtle)", textAlign: "left", fontSize: 14, minHeight: 72 }}>
                    e.g. I want to become a machine learning engineer…
                  </div>
                  <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                    <div style={{ background: "var(--grad-primary)", borderRadius: "var(--r-md)", padding: "10px 20px", color: "#fff", fontSize: 14, fontWeight: 600 }}>🚀 Find My Path</div>
                  </div>
                </div>
                <div style={{ position: "absolute", inset: 0, borderRadius: "var(--r-lg)", background: "linear-gradient(to bottom, transparent 0%, rgba(7,11,20,0.4) 100%)" }} />
              </div>

              <div className="flex gap-md">
                <a href="#/login" className="btn btn-ghost">Sign In</a>
                <a href="#/register" className="btn btn-primary">Create Free Account →</a>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: "var(--sp-md)", width: "100%", marginTop: "var(--sp-sm)" }}>
                {[
                  { icon: "🤖", title: "AI Pathfinder", desc: "Personalized course sequences built by LangGraph" },
                  { icon: "📊", title: "Skill Gap Analysis", desc: "Know exactly what to learn next" },
                  { icon: "🗺️", title: "Learning Roadmap", desc: "Step-by-step ordered learning path" },
                ].map((f) => (
                  <div key={f.title} className="glass" style={{ padding: "var(--sp-md)", textAlign: "left" }}>
                    <div style={{ fontSize: 24, marginBottom: 6 }}>{f.icon}</div>
                    <div style={{ fontWeight: 600, fontSize: 14, color: "var(--clr-text)", marginBottom: 4 }}>{f.title}</div>
                    <div style={{ fontSize: 12, color: "var(--clr-muted)" }}>{f.desc}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            /* ── Logged-in Search Box ── */
            <>
              <div className="glass search-inner">
                <textarea
                  id="goal-input"
                  rows={3}
                  placeholder="e.g. I'm a backend developer who wants to transition into machine learning. I know Python and basic statistics…"
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(); } }}
                />

                {/* Filters */}
                {meta && (
                  <div className="filters-panel" style={{ padding: "0 0 8px" }}>
                    <div className="filter-group">
                      <span className="filter-label">Difficulty</span>
                      <select className="form-select" style={{ fontSize: 13, padding: "6px 10px" }}
                        value={filters.difficulty} onChange={(e) => setFilters({ ...filters, difficulty: e.target.value })}>
                        <option value="">Any</option>
                        {meta.difficulties?.map((d) => <option key={d} value={d}>{d}</option>)}
                      </select>
                    </div>
                    <div className="filter-group">
                      <span className="filter-label">Category</span>
                      <select className="form-select" style={{ fontSize: 13, padding: "6px 10px" }}
                        value={filters.category} onChange={(e) => setFilters({ ...filters, category: e.target.value })}>
                        <option value="">Any</option>
                        {meta.categories?.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                    <div className="filter-group">
                      <span className="filter-label">Max weeks</span>
                      <input className="form-input" type="number" placeholder="e.g. 8" style={{ fontSize: 13, padding: "6px 10px" }}
                        value={filters.max_weeks} onChange={(e) => setFilters({ ...filters, max_weeks: e.target.value })} />
                    </div>
                    <div className="filter-group">
                      <span className="filter-label">Min rating</span>
                      <input className="form-input" type="number" step="0.1" min="0" max="5" placeholder="e.g. 4.5" style={{ fontSize: 13, padding: "6px 10px" }}
                        value={filters.min_rating} onChange={(e) => setFilters({ ...filters, min_rating: e.target.value })} />
                    </div>
                  </div>
                )}

                <div className="search-actions">
                  <span className="search-meta">
                    {busy ? "⚡ AI is analyzing your goal…" : "Press Enter or click Find My Path"}
                  </span>
                  <button id="find-path-btn" className="btn btn-primary" disabled={busy} onClick={() => run()}>
                    {busy ? <><div className="spinner" /> Thinking…</> : "🚀 Find My Path"}
                  </button>
                </div>
              </div>

              {/* Search History */}
              {history.length > 0 && (
                <div className="search-history-section">
                  <div className="search-history-header">
                    <span className="search-history-label">🕒 Recent Searches</span>
                    <button className="btn btn-ghost btn-xs" style={{ fontSize: 11, padding: "2px 8px" }} onClick={clearHistory}>
                      Clear history
                    </button>
                  </div>
                  <div className="search-history-chips">
                    {history.map((h, i) => (
                      <button key={i} className="history-chip" onClick={() => { setGoal(h); run(h); }}>
                        🔍 {h}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Suggested Examples */}
              <div className="search-examples">
                {EXAMPLES.map((x) => (
                  <button key={x} className="example-chip" onClick={() => { setGoal(x); run(x); }}>{x}</button>
                ))}
              </div>

              {err && <div className="alert alert-error mt-md">⚠️ {err}</div>}
            </>
          )}
        </div>

        {/* Results */}
        {res && (
          <div className="results">
            {/* Summary */}
            <div className="result-section glass">
              <div className="section-header summary-text">
                <div className="section-icon si-blue">🤖</div>
                <div>
                  <h3 style={{ margin: 0 }}>AI Summary</h3>
                  <p style={{ margin: 0, fontSize: 14 }}>{res.summary}</p>
                </div>
              </div>
              {res.trace?.length > 0 && (
                <details className="agent-trace">
                  <summary>🔍 Agent reasoning ({res.trace.length} steps)</summary>
                  <ol>{res.trace.map((t, i) => <li key={i}>{t}</li>)}</ol>
                </details>
              )}
            </div>

            {/* Skill Gap */}
            <div className="result-section">
              <div className="section-header">
                <div className="section-icon si-cyan">🧠</div>
                <h2>Skill Analysis</h2>
              </div>
              <div className="glass" style={{ padding: "var(--sp-md)" }}>
                <div className="skill-chips">
                  {res.known_skills?.map((s) => <span key={s} className="skill-chip known">✓ {s}</span>)}
                  {res.gap_skills?.map((s) => (
                    <span key={s} className={`skill-chip ${res.uncovered?.includes(s) ? "uncovered" : "gap"}`}>
                      {res.uncovered?.includes(s) ? "○" : "△"} {s}
                    </span>
                  ))}
                </div>
                <p className="text-sm text-muted mt-md">
                  ✅ Green = you have it &nbsp;·&nbsp; 🟡 Amber = to learn &nbsp;·&nbsp; ⬜ Dashed = no course available
                </p>
              </div>
            </div>

            {/* Learning Path */}
            {res.path?.length > 0 && (
              <div className="result-section">
                <div className="section-header">
                  <div className="section-icon si-purple">🗺️</div>
                  <h2>Your Learning Path</h2>
                </div>
                <div className="learning-path">
                  {res.path.map((c, i) => (
                    <div key={c.course_id} className="path-item">
                      <div className="path-step-num">{i + 1}</div>
                      <div>
                        <div className="path-stage-label">
                          {c.stage}{c.kind === "prerequisite" ? " · Prerequisite" : ""}
                        </div>
                        <CourseCard
                          c={c}
                          query={res.goal}
                          onBookmark={toggleBookmark}
                          bookmarked={bookmarks.has(c.course_id)}
                          onEnroll={handleEnroll}
                          isEnrolled={enrolledSet.has(c.course_id)}
                        />
                        {c.fills?.length > 0 && (
                          <p className="text-sm text-muted mt-md">
                            📌 Closes skill gap: {c.fills.join(", ")}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Best Matches */}
            {res.hits?.length > 0 && (
              <div className="result-section">
                <div className="section-header">
                  <div className="section-icon si-green">⭐</div>
                  <h2>Best Matches</h2>
                </div>
                <div className="courses-grid">
                  {res.hits.map((c) => (
                    <CourseCard
                      key={c.course_id}
                      c={c}
                      query={res.goal}
                      onBookmark={toggleBookmark}
                      bookmarked={bookmarks.has(c.course_id)}
                      onEnroll={handleEnroll}
                      isEnrolled={enrolledSet.has(c.course_id)}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── User Dashboard ─────────────────────────────────────────────────────── */
function DashboardPage() {
  const { user, addToast } = useAuth();
  const [enrollments, setEnrollments] = useState([]);
  const [bookmarks, setBookmarks] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchDashboard = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get("/user/enrollments"),
      api.get("/user/bookmarks"),
    ])
      .then(([e, b]) => {
        setEnrollments(e.enrollments || []);
        setBookmarks(b.bookmarks || []);
      })
      .catch((err) => {
        console.error("Dashboard fetch error:", err);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  const updateProgress = async (eid, newProg) => {
    try {
      await api.put(`/user/enrollments/${eid}/progress?progress=${newProg}`);
      setEnrollments((prev) =>
        prev.map((e) => (e.id === eid ? { ...e, progress: newProg, completed_at: newProg >= 100 ? Date.now() / 1000 : null } : e))
      );
      addToast(newProg >= 100 ? "Course marked complete! 🏆" : `Progress updated to ${newProg}% 📈`);
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  const removeBookmark = async (courseId) => {
    try {
      await api.post("/user/bookmark", { course_id: courseId, action: "remove" });
      setBookmarks((prev) => prev.filter((b) => b.course_id !== courseId));
      addToast("Bookmark removed", "info");
    } catch (err) {
      addToast(err.message, "error");
    }
  };

  if (loading) return <LoadingScreen />;

  return (
    <div className="container" style={{ padding: "40px var(--sp-lg)" }}>
      <div style={{ marginBottom: "var(--sp-xl)" }}>
        <div className="hero-badge" style={{ display: "inline-flex", marginBottom: "var(--sp-md)" }}>
          <span>👋</span> <span>Welcome back, {user?.full_name || user?.username}</span>
        </div>
        <h2>My Learning Hub</h2>
        <p>Track your progress and manage your saved courses</p>
      </div>

      {/* Stats */}
      <div className="stats-grid">
        <div className="glass stat-card">
          <div className="stat-icon si-blue">📚</div>
          <div className="stat-value">{enrollments.length}</div>
          <div className="stat-label">Enrolled Courses</div>
        </div>
        <div className="glass stat-card">
          <div className="stat-icon si-green">✅</div>
          <div className="stat-value">{enrollments.filter((e) => e.progress >= 100).length}</div>
          <div className="stat-label">Completed</div>
        </div>
        <div className="glass stat-card">
          <div className="stat-icon si-cyan">★</div>
          <div className="stat-value">{bookmarks.length}</div>
          <div className="stat-label">Bookmarked</div>
        </div>
        <div className="glass stat-card">
          <div className="stat-icon si-purple">📈</div>
          <div className="stat-value">
            {enrollments.length ? Math.round(enrollments.reduce((a, e) => a + e.progress, 0) / enrollments.length) : 0}%
          </div>
          <div className="stat-label">Avg. Progress</div>
        </div>
      </div>

      {/* Enrollments */}
      <div style={{ marginBottom: "var(--sp-xl)" }}>
        <h3 style={{ marginBottom: "var(--sp-md)" }}>📚 My Enrollments</h3>
        {enrollments.length === 0 ? (
          <div className="glass" style={{ padding: "var(--sp-xl)", textAlign: "center" }}>
            <p>No enrollments yet. <a href="#/" style={{ cursor: "pointer" }}>Find your first course →</a></p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Course Title</th>
                  <th>Category</th>
                  <th>Progress</th>
                  <th>Enrolled Date</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {enrollments.map((e) => {
                  const meta = e.course_meta || {};
                  return (
                    <tr key={e.id}>
                      <td>
                        <div style={{ fontWeight: 600, color: "var(--clr-text)" }}>
                          {meta.url ? (
                            <a href={meta.url} target="_blank" rel="noreferrer" style={{ color: "var(--clr-primary-h)" }}>
                              {meta.title || e.course_id}
                            </a>
                          ) : (
                            meta.title || e.course_id
                          )}
                        </div>
                        <div className="text-muted text-sm">{meta.organization || "Catalog"} · {meta.difficulty || "All Levels"}</div>
                      </td>
                      <td><span className="badge badge-user">{meta.category || e.source}</span></td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 160 }}>
                          <div style={{ flex: 1, height: 7, background: "rgba(255,255,255,0.1)", borderRadius: 4, overflow: "hidden" }}>
                            <div style={{ width: `${e.progress}%`, height: "100%", background: "var(--grad-primary)", borderRadius: 4 }} />
                          </div>
                          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--clr-muted)" }}>{e.progress}%</span>
                        </div>
                      </td>
                      <td className="text-muted text-sm">{new Date(e.enrolled_at * 1000).toLocaleDateString()}</td>
                      <td>
                        <div className="flex gap-sm">
                          {e.progress < 100 ? (
                            <button
                              className="btn btn-primary btn-sm"
                              style={{ padding: "4px 10px", fontSize: 12 }}
                              onClick={() => updateProgress(e.id, Math.min(100, e.progress + 25))}
                            >
                              +25% Progress
                            </button>
                          ) : (
                            <span className="badge badge-active">🏆 Completed</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Bookmarks */}
      <div>
        <h3 style={{ marginBottom: "var(--sp-md)" }}>★ Bookmarked Courses</h3>
        {bookmarks.length === 0 ? (
          <div className="glass" style={{ padding: "var(--sp-xl)", textAlign: "center" }}>
            <p>No bookmarks yet. Bookmark courses while searching to save them here.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Course Title</th>
                  <th>Category</th>
                  <th>Saved Date</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {bookmarks.map((b) => {
                  const meta = b.course_meta || {};
                  return (
                    <tr key={b.id}>
                      <td>
                        <div style={{ fontWeight: 600, color: "var(--clr-text)" }}>
                          {meta.url ? (
                            <a href={meta.url} target="_blank" rel="noreferrer" style={{ color: "var(--clr-primary-h)" }}>
                              {meta.title || b.course_id}
                            </a>
                          ) : (
                            meta.title || b.course_id
                          )}
                        </div>
                        <div className="text-muted text-sm">{meta.organization || "Catalog"} · {meta.difficulty || "All Levels"}</div>
                      </td>
                      <td><span className="badge badge-user">{meta.category || b.source}</span></td>
                      <td className="text-muted text-sm">{new Date(b.created_at * 1000).toLocaleDateString()}</td>
                      <td>
                        <button
                          className="btn btn-ghost btn-sm"
                          style={{ padding: "4px 10px", fontSize: 12, color: "var(--clr-error)" }}
                          onClick={() => removeBookmark(b.course_id)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Admin Dashboard ────────────────────────────────────────────────────── */
function AdminPage({ initialTab }) {
  const [tab, setTab] = useState(initialTab || "overview");

  const tabs = [
    { id: "overview",  label: "Overview",     icon: "📊" },
    { id: "courses",   label: "Courses",       icon: "📚" },
    { id: "users",     label: "Users",         icon: "👥" },
    { id: "activity",  label: "Activity Log",  icon: "📋" },
  ];

  return (
    <div className="admin-layout">
      {/* Sidebar */}
      <aside className="admin-sidebar">
        <div className="sidebar-label">Management</div>
        {tabs.map((t) => (
          <button key={t.id} className={`sidebar-item ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>
            <span>{t.icon}</span> {t.label}
          </button>
        ))}
      </aside>

      {/* Content */}
      <main className="admin-content">
        {tab === "overview" && <AdminOverview />}
        {tab === "courses"  && <AdminCourses />}
        {tab === "users"    && <AdminUsers />}
        {tab === "activity" && <AdminActivity />}
      </main>
    </div>
  );
}

/* ─── Admin Overview ─────────────────────────────────────────────────────── */
function AdminOverview() {
  const [stats, setStats] = useState(null);

  useEffect(() => { api.get("/admin/stats").then(setStats).catch(() => {}); }, []);

  if (!stats) return <LoadingScreen />;

  return (
    <div>
      <h2 style={{ marginBottom: "var(--sp-xl)" }}>⚡ Admin Dashboard</h2>
      <div className="stats-grid">
        {[
          { icon: "👤", value: stats.users_total, label: "Total Users", color: "si-blue" },
          { icon: "🛡️", value: stats.admins_total, label: "Admins", color: "si-purple" },
          { icon: "📚", value: stats.courses_total, label: "Admin Courses", color: "si-cyan" },
          { icon: "🎓", value: stats.enrollments_total, label: "Enrollments", color: "si-green" },
          { icon: "★",  value: stats.bookmarks_total, label: "Bookmarks", color: "si-blue" },
          { icon: "⚡", value: stats.active_today, label: "Active Today", color: "si-purple" },
        ].map((s) => (
          <div key={s.label} className="glass stat-card">
            <div className={`stat-icon ${s.color}`}>{s.icon}</div>
            <div className="stat-value">{s.value}</div>
            <div className="stat-label">{s.label}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--sp-lg)" }}>
        <div>
          <h3 style={{ marginBottom: "var(--sp-md)" }}>Recent Users</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>User</th><th>Role</th><th>Joined</th></tr></thead>
              <tbody>
                {stats.recent_users.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <div className="flex items-center gap-sm">
                        <div className="nav-avatar" style={{ width: 28, height: 28, fontSize: 11 }}>{u.username[0].toUpperCase()}</div>
                        <div>
                          <div className="fw-600" style={{ fontSize: 13 }}>{u.username}</div>
                          <div className="text-muted text-sm">{u.email}</div>
                        </div>
                      </div>
                    </td>
                    <td><span className={`badge badge-${u.role}`}>{u.role}</span></td>
                    <td className="text-muted text-sm">{new Date(u.created_at * 1000).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <h3 style={{ marginBottom: "var(--sp-md)" }}>Recent Enrollments</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>User</th><th>Course</th><th>Date</th></tr></thead>
              <tbody>
                {stats.recent_enrollments.map((e) => (
                  <tr key={e.id}>
                    <td className="fw-600" style={{ fontSize: 13 }}>{e.username}</td>
                    <td className="text-muted text-sm" style={{ maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.course_id}</td>
                    <td className="text-muted text-sm">{new Date(e.enrolled_at * 1000).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── Admin Courses CRUD ─────────────────────────────────────────────────── */
const DIFFICULTIES = ["Beginner", "Intermediate", "Advanced", "Mixed"];
const COURSE_TYPES = ["Course", "Specialization", "Professional Certificate", "MicroDegree", "Guided Project"];

function AdminCourses() {
  const { addToast } = useAuth();
  const [courses, setCourses] = useState([]);
  const [total, setTotal] = useState(0);
  const [modal, setModal] = useState(null); // null | "add" | course obj
  const [delId, setDelId] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.get("/admin/courses?limit=100").then((r) => { setCourses(r.courses); setTotal(r.total); }).finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleSave = async (data) => {
    try {
      if (modal === "add") {
        await api.post("/admin/courses", data);
        addToast("Course created ✅");
      } else {
        await api.put(`/admin/courses/${modal.id}`, data);
        addToast("Course updated ✅");
      }
      setModal(null);
      load();
    } catch (e) { addToast(e.message, "error"); }
  };

  const handleDelete = async () => {
    try {
      await api.del(`/admin/courses/${delId}`);
      addToast("Course deleted");
      setDelId(null);
      load();
    } catch (e) { addToast(e.message, "error"); }
  };

  return (
    <div>
      <div className="flex items-center justify-between" style={{ marginBottom: "var(--sp-xl)" }}>
        <div>
          <h2>📚 Course Management</h2>
          <p className="text-muted text-sm">{total} courses in admin catalog</p>
        </div>
        <button id="add-course-btn" className="btn btn-primary" onClick={() => setModal("add")}>+ Add Course</button>
      </div>

      {loading ? <LoadingScreen /> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Title</th><th>Organization</th><th>Category</th><th>Difficulty</th>
                <th>Rating</th><th>Status</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {courses.map((c) => (
                <tr key={c.id}>
                  <td>
                    <div className="fw-600" style={{ fontSize: 14 }}>{c.title}</div>
                    {c.url && <a href={c.url} target="_blank" rel="noreferrer" className="text-sm" style={{ color: "var(--clr-primary-h)" }}>🔗 Link</a>}
                  </td>
                  <td className="text-muted text-sm">{c.organization || "—"}</td>
                  <td className="text-muted text-sm">{c.category || "—"}</td>
                  <td><span className={`diff-badge diff-${(c.difficulty || "").toLowerCase()}`}>{c.difficulty}</span></td>
                  <td className="text-muted text-sm">{c.rating ? `★ ${c.rating}` : "—"}</td>
                  <td><span className={`badge badge-${c.is_active ? "active" : "inactive"}`}>{c.is_active ? "Active" : "Draft"}</span></td>
                  <td>
                    <div className="flex gap-sm">
                      <button className="btn btn-ghost btn-sm" onClick={() => setModal(c)}>Edit</button>
                      <button className="btn btn-danger btn-sm" onClick={() => setDelId(c.id)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {courses.length === 0 && (
                <tr><td colSpan={7} style={{ textAlign: "center", padding: "var(--sp-xl)", color: "var(--clr-muted)" }}>
                  No courses yet. Click "+ Add Course" to get started.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Course Modal */}
      {modal && (
        <CourseModal
          course={modal === "add" ? null : modal}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}

      {/* Delete Confirm */}
      {delId && (
        <div className="modal-backdrop" onClick={() => setDelId(null)}>
          <div className="glass modal" style={{ maxWidth: 400 }} onClick={(e) => e.stopPropagation()}>
            <h3>🗑️ Delete Course?</h3>
            <p>This action cannot be undone. The course will be permanently removed from the admin catalog.</p>
            <div className="flex gap-sm" style={{ justifyContent: "flex-end" }}>
              <button className="btn btn-ghost" onClick={() => setDelId(null)}>Cancel</button>
              <button className="btn btn-danger" onClick={handleDelete}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CourseModal({ course, onSave, onClose }) {
  const [form, setForm] = useState({
    title: course?.title || "",
    description: course?.description || "",
    organization: course?.organization || "",
    category: course?.category || "",
    difficulty: course?.difficulty || "Beginner",
    course_type: course?.course_type || "Course",
    url: course?.url || "",
    duration_weeks_min: course?.duration_weeks_min || "",
    duration_weeks_max: course?.duration_weeks_max || "",
    rating: course?.rating || "",
    skills: course?.skills?.join(", ") || "",
    is_active: course ? Boolean(course.is_active) : true,
  });
  const [saving, setSaving] = useState(false);

  const F = (key, type = "text") => ({
    value: form[key],
    onChange: (e) => setForm({ ...form, [key]: type === "bool" ? e.target.checked : e.target.value }),
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    await onSave({
      ...form,
      duration_weeks_min: form.duration_weeks_min ? parseFloat(form.duration_weeks_min) : null,
      duration_weeks_max: form.duration_weeks_max ? parseFloat(form.duration_weeks_max) : null,
      rating: form.rating ? parseFloat(form.rating) : null,
      skills: form.skills.split(",").map((s) => s.trim()).filter(Boolean),
      is_active: form.is_active,
    });
    setSaving(false);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="glass modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{course ? "✏️ Edit Course" : "➕ Add New Course"}</h3>
          <button className="btn btn-ghost btn-icon" onClick={onClose}>✕</button>
        </div>

        <form className="modal-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Title *</label>
            <input id="course-title" className="form-input" required {...F("title")} placeholder="Introduction to Machine Learning" />
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Organization</label>
              <input id="course-org" className="form-input" {...F("organization")} placeholder="Coursera / edX / Udemy…" />
            </div>
            <div className="form-group">
              <label className="form-label">Category</label>
              <input id="course-category" className="form-input" {...F("category")} placeholder="Data Science" />
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Difficulty</label>
              <select id="course-difficulty" className="form-select" {...F("difficulty")}>
                {DIFFICULTIES.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Type</label>
              <select id="course-type" className="form-select" {...F("course_type")}>
                {COURSE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Course URL</label>
            <input id="course-url" className="form-input" type="url" {...F("url")} placeholder="https://www.coursera.org/learn/…" />
          </div>

          <div className="form-group">
            <label className="form-label">Description</label>
            <textarea id="course-desc" className="form-textarea" rows={3} {...F("description")} placeholder="Describe what students will learn…" />
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Duration (weeks min)</label>
              <input id="course-dur-min" className="form-input" type="number" step="0.5" {...F("duration_weeks_min")} placeholder="e.g. 4" />
            </div>
            <div className="form-group">
              <label className="form-label">Duration (weeks max)</label>
              <input id="course-dur-max" className="form-input" type="number" step="0.5" {...F("duration_weeks_max")} placeholder="e.g. 8" />
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Rating (0–5)</label>
              <input id="course-rating" className="form-input" type="number" step="0.1" min="0" max="5" {...F("rating")} placeholder="4.7" />
            </div>
            <div className="form-group" style={{ justifyContent: "flex-end" }}>
              <label className="form-label">Status</label>
              <div className="flex items-center gap-sm" style={{ paddingTop: 10 }}>
                <input id="course-active" type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} style={{ width: 16, height: 16, cursor: "pointer" }} />
                <span style={{ fontSize: 14, color: form.is_active ? "var(--clr-success)" : "var(--clr-muted)" }}>
                  {form.is_active ? "Active" : "Draft"}
                </span>
              </div>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Skills (comma-separated)</label>
            <input id="course-skills" className="form-input" {...F("skills")} placeholder="Python, Machine Learning, Neural Networks…" />
          </div>

          <div className="flex gap-sm" style={{ justifyContent: "flex-end", marginTop: 8 }}>
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button id="save-course-btn" type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? <><div className="spinner" /> Saving…</> : `${course ? "Update" : "Create"} Course`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ─── Admin Users ────────────────────────────────────────────────────────── */
function AdminUsers() {
  const { addToast } = useAuth();
  const [users, setUsers] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.get("/admin/users?limit=100").then((r) => { setUsers(r.users); setTotal(r.total); }).finally(() => setLoading(false));
  };

  useEffect(load, []);

  const toggleStatus = async (u) => {
    try {
      await api.put(`/admin/users/${u.id}`, { is_active: !u.is_active });
      addToast(`User ${u.is_active ? "deactivated" : "activated"}`);
      load();
    } catch (e) { addToast(e.message, "error"); }
  };

  const toggleRole = async (u) => {
    try {
      await api.put(`/admin/users/${u.id}`, { role: u.role === "admin" ? "user" : "admin" });
      addToast("Role updated");
      load();
    } catch (e) { addToast(e.message, "error"); }
  };

  return (
    <div>
      <div style={{ marginBottom: "var(--sp-xl)" }}>
        <h2>👥 User Management</h2>
        <p className="text-muted text-sm">{total} registered users</p>
      </div>

      {loading ? <LoadingScreen /> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>User</th><th>Role</th><th>Status</th><th>Joined</th><th>Last Login</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>
                    <div className="flex items-center gap-sm">
                      <div className="nav-avatar" style={{ width: 32, height: 32, fontSize: 13 }}>{u.username[0].toUpperCase()}</div>
                      <div>
                        <div className="fw-600" style={{ fontSize: 14 }}>{u.full_name || u.username}</div>
                        <div className="text-muted text-sm">@{u.username} · {u.email}</div>
                      </div>
                    </div>
                  </td>
                  <td><span className={`badge badge-${u.role}`}>{u.role}</span></td>
                  <td><span className={`badge badge-${u.is_active ? "active" : "inactive"}`}>{u.is_active ? "Active" : "Disabled"}</span></td>
                  <td className="text-muted text-sm">{new Date(u.created_at * 1000).toLocaleDateString()}</td>
                  <td className="text-muted text-sm">{u.last_login ? new Date(u.last_login * 1000).toLocaleDateString() : "Never"}</td>
                  <td>
                    <div className="flex gap-sm">
                      <button className="btn btn-ghost btn-sm" onClick={() => toggleRole(u)}>
                        {u.role === "admin" ? "→ User" : "→ Admin"}
                      </button>
                      <button className={`btn btn-sm ${u.is_active ? "btn-danger" : "btn-success"}`} onClick={() => toggleStatus(u)}>
                        {u.is_active ? "Disable" : "Enable"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ─── Admin Activity Log ─────────────────────────────────────────────────── */
function AdminActivity() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/admin/activity?limit=100").then((r) => setLogs(r.activity)).finally(() => setLoading(false));
  }, []);

  const actionColor = {
    login: "si-green", register: "si-blue", search: "si-cyan",
    plan: "si-purple", course_create: "si-blue", course_update: "si-cyan",
    course_delete: "si-purple", scrape: "si-purple",
  };

  return (
    <div>
      <div style={{ marginBottom: "var(--sp-xl)" }}>
        <h2>📋 Activity Log</h2>
        <p className="text-muted text-sm">Recent platform activity</p>
      </div>

      {loading ? <LoadingScreen /> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Detail</th><th>IP</th></tr></thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id}>
                  <td className="text-muted text-sm" style={{ whiteSpace: "nowrap" }}>
                    {new Date(l.ts * 1000).toLocaleString()}
                  </td>
                  <td className="fw-600" style={{ fontSize: 13 }}>{l.username || "—"}</td>
                  <td>
                    <span className={`section-icon ${actionColor[l.action] || "si-blue"}`} style={{ display: "inline-flex", width: "auto", height: "auto", padding: "2px 8px", borderRadius: "var(--r-full)", fontSize: 12, fontWeight: 600 }}>
                      {l.action}
                    </span>
                  </td>
                  <td className="text-muted text-sm" style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.detail || "—"}</td>
                  <td className="text-muted text-sm">{l.ip || "—"}</td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr><td colSpan={5} style={{ textAlign: "center", padding: "var(--sp-xl)", color: "var(--clr-muted)" }}>No activity yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ─── Shared Loading ─────────────────────────────────────────────────────── */
function LoadingScreen() {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "var(--sp-2xl)", gap: "var(--sp-md)" }}>
      <div className="spinner" style={{ width: 24, height: 24, borderColor: "rgba(99,102,241,0.3)", borderTopColor: "var(--clr-primary)" }} />
      <span className="text-muted">Loading…</span>
    </div>
  );
}

/* ─── 404 Page ───────────────────────────────────────────────────────────── */
function NotFoundPage({ navigate }) {
  return (
    <div style={{ textAlign: "center", padding: "var(--sp-2xl)" }}>
      <div style={{ fontSize: 64, marginBottom: "var(--sp-md)" }}>🌌</div>
      <h2>Page Not Found</h2>
      <p className="text-muted" style={{ marginBottom: "var(--sp-lg)" }}>The route you're looking for doesn't exist.</p>
      <button className="btn btn-primary" onClick={() => navigate("/")}>← Back Home</button>
    </div>
  );
}

/* ─── Protected Route ────────────────────────────────────────────────────── */
function Protected({ children, navigate, adminOnly }) {
  const { user } = useAuth();
  if (!user) { navigate("/login"); return null; }
  if (adminOnly && user.role !== "admin") { navigate("/"); return null; }
  return children;
}

/* ─── App Root ───────────────────────────────────────────────────────────── */
function Router() {
  const { route, navigate } = useRoute();

  const renderPage = () => {
    if (route === "/" || route === "")         return <FinderPage />;
    if (route === "/login")                    return <LoginPage navigate={navigate} />;
    if (route === "/register")                 return <RegisterPage navigate={navigate} />;
    if (route === "/dashboard")                return <Protected navigate={navigate}><DashboardPage /></Protected>;
    if (route.startsWith("/admin"))            return <Protected navigate={navigate} adminOnly><AdminPage /></Protected>;
    return <NotFoundPage navigate={navigate} />;
  };

  const hideNav = route === "/login" || route === "/register";

  return (
    <div className="page">
      {!hideNav && <Navbar route={route} navigate={navigate} />}
      {renderPage()}
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Router />
    </AuthProvider>
  );
}