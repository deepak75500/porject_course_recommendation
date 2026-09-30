"""
Authentication module: SQLite3 user store, JWT tokens, bcrypt hashing.
Architecture: stateless JWT (access + refresh pattern), role-based access (admin | user).
"""
import os, sqlite3, hashlib, hmac, time, base64, json, pathlib, secrets
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

DB_PATH = pathlib.Path(__file__).parent / "data" / "app.db"
SECRET = os.getenv("JWT_SECRET", "course_finder_fallback_secret_key_2026_fixed")
ACCESS_TTL = 60 * 60 * 24 * 7   # 7 days
REFRESH_TTL = 60 * 60 * 24 * 30  # 30 days

bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Database bootstrap
# ---------------------------------------------------------------------------

def get_db():
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email       TEXT    UNIQUE NOT NULL,
            username    TEXT    UNIQUE NOT NULL,
            password_hash TEXT  NOT NULL,
            role        TEXT    NOT NULL DEFAULT 'user',
            full_name   TEXT    DEFAULT '',
            avatar_url  TEXT    DEFAULT '',
            bio         TEXT    DEFAULT '',
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  REAL    NOT NULL,
            last_login  REAL
        );

        CREATE TABLE IF NOT EXISTS admin_courses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            organization TEXT   NOT NULL DEFAULT '',
            category    TEXT    NOT NULL DEFAULT '',
            difficulty  TEXT    NOT NULL DEFAULT 'Beginner',
            course_type TEXT    NOT NULL DEFAULT 'Course',
            url         TEXT    DEFAULT '',
            duration_weeks_min REAL,
            duration_weeks_max REAL,
            rating      REAL,
            skills      TEXT    DEFAULT '[]',
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_by  INTEGER REFERENCES users(id),
            created_at  REAL    NOT NULL,
            updated_at  REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS enrollments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            course_id   TEXT    NOT NULL,
            source      TEXT    NOT NULL DEFAULT 'catalog',
            enrolled_at REAL    NOT NULL,
            progress    INTEGER NOT NULL DEFAULT 0,
            completed_at REAL,
            UNIQUE(user_id, course_id)
        );

        CREATE TABLE IF NOT EXISTS bookmarks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            course_id   TEXT    NOT NULL,
            source      TEXT    NOT NULL DEFAULT 'catalog',
            created_at  REAL    NOT NULL,
            UNIQUE(user_id, course_id)
        );

        CREATE TABLE IF NOT EXISTS activity_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id),
            action      TEXT    NOT NULL,
            detail      TEXT    DEFAULT '',
            ip          TEXT    DEFAULT '',
            ts          REAL    NOT NULL
        );
    """)
    db.commit()

    # Seed default admin if none exists
    cur = db.execute("SELECT id FROM users WHERE role='admin' LIMIT 1")
    if not cur.fetchone():
        phash = _hash_password("admin123")
        db.execute(
            "INSERT INTO users (email, username, password_hash, role, full_name, created_at) VALUES (?,?,?,?,?,?)",
            ("admin@coursefinder.ai", "admin", phash, "admin", "System Admin", time.time())
        )
        db.commit()
        print("✅ Default admin created: admin@coursefinder.ai / admin123  ← CHANGE IN PRODUCTION")
    db.close()


# ---------------------------------------------------------------------------
# Password hashing  (PBKDF2-HMAC-SHA256 — no bcrypt dependency needed)
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2$sha256$260000${salt}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, algo, iters, salt, encoded = stored.split("$")
        dk = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(base64.b64encode(dk).decode(), encoded)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT  (pure-stdlib HS256 — no PyJWT needed)
# ---------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _from_b64url(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (pad % 4))


def create_token(payload: dict, ttl: int = ACCESS_TTL) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = {**payload, "iat": int(time.time()), "exp": int(time.time()) + ttl}
    body = _b64url(json.dumps(payload).encode())
    sig = _b64url(hmac.new(SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def decode_token(token: str) -> dict:
    try:
        h, b, s = token.split(".")
        expected = _b64url(hmac.new(SECRET.encode(), f"{h}.{b}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, s):
            raise ValueError("bad signature")
        payload = json.loads(_from_b64url(b))
        if payload.get("exp", 0) < time.time():
            raise ValueError("token expired")
        return payload
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)):
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return decode_token(creds.credentials)


def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


def optional_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)):
    if not creds:
        return None
    try:
        return decode_token(creds.credentials)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# User CRUD helpers
# ---------------------------------------------------------------------------

def create_user(email: str, username: str, password: str, full_name: str = "", role: str = "user"):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (email, username, password_hash, role, full_name, created_at) VALUES (?,?,?,?,?,?)",
            (email.lower(), username, _hash_password(password), role, full_name, time.time())
        )
        db.commit()
        return db.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
    except sqlite3.IntegrityError as e:
        raise HTTPException(400, f"Email or username already taken: {e}")
    finally:
        db.close()


def authenticate_user(email_or_username: str, password: str):
    db = get_db()
    try:
        u = db.execute(
            "SELECT * FROM users WHERE (email=? OR username=?) AND is_active=1",
            (email_or_username.lower(), email_or_username)
        ).fetchone()
        if not u or not verify_password(password, u["password_hash"]):
            return None
        db.execute("UPDATE users SET last_login=? WHERE id=?", (time.time(), u["id"]))
        db.commit()
        return dict(u)
    finally:
        db.close()


def get_user_by_id(uid: int):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def log_activity(user_id, action: str, detail: str = "", ip: str = ""):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO activity_log (user_id, action, detail, ip, ts) VALUES (?,?,?,?,?)",
            (user_id, action, detail, ip, time.time())
        )
        db.commit()
    finally:
        db.close()
