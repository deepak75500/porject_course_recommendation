"""
Admin & Auth API router — attaches to the main FastAPI app.
Endpoints:
  POST /auth/register         public
  POST /auth/login            public
  GET  /auth/me               authenticated
  PUT  /auth/me               authenticated
  GET  /admin/users           admin
  PUT  /admin/users/{id}      admin
  DELETE /admin/users/{id}    admin
  GET  /admin/courses         admin
  POST /admin/courses         admin
  PUT  /admin/courses/{id}    admin
  DELETE /admin/courses/{id}  admin
  GET  /admin/stats           admin
  GET  /admin/activity        admin
  POST /user/enroll           user
  GET  /user/enrollments      user
  POST /user/bookmark         user
  GET  /user/bookmarks        user
"""
import json, time, sqlite3
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, EmailStr, field_validator
import auth

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RegisterBody(BaseModel):
    email: str
    username: str
    password: str
    full_name: str = ""

    @field_validator("password")
    @classmethod
    def pw_strength(cls, v):
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v

    @field_validator("username")
    @classmethod
    def username_clean(cls, v):
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username may only contain letters, numbers, _ or -")
        return v.lower()


class LoginBody(BaseModel):
    email_or_username: str
    password: str


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None


class AdminCourseBody(BaseModel):
    title: str
    description: str = ""
    organization: str = ""
    category: str = ""
    difficulty: str = "Beginner"
    course_type: str = "Course"
    url: str = ""
    duration_weeks_min: Optional[float] = None
    duration_weeks_max: Optional[float] = None
    rating: Optional[float] = None
    skills: List[str] = []
    is_active: bool = True


class EnrollBody(BaseModel):
    course_id: str
    source: str = "catalog"


class BookmarkBody(BaseModel):
    course_id: str
    source: str = "catalog"
    action: str = "add"  # add | remove


class UpdateUserBody(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    full_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@router.post("/auth/register", status_code=201)
def register(body: RegisterBody, request: Request):
    user = auth.create_user(body.email, body.username, body.password, body.full_name)
    auth.log_activity(user["id"], "register", body.email, request.client.host if request.client else "")
    token = auth.create_token({"sub": user["id"], "role": user["role"], "username": user["username"]})
    return {"access_token": token, "token_type": "bearer",
            "user": _safe_user(dict(user))}


@router.post("/auth/login")
def login(body: LoginBody, request: Request):
    user = auth.authenticate_user(body.email_or_username, body.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    auth.log_activity(user["id"], "login", "", request.client.host if request.client else "")
    token = auth.create_token({"sub": user["id"], "role": user["role"], "username": user["username"]})
    return {"access_token": token, "token_type": "bearer",
            "user": _safe_user(user)}


@router.get("/auth/me")
def me(current=Depends(auth.get_current_user)):
    user = auth.get_user_by_id(current["sub"])
    if not user:
        raise HTTPException(404, "User not found")
    return _safe_user(user)


@router.put("/auth/me")
def update_me(body: ProfileUpdate, current=Depends(auth.get_current_user)):
    db = auth.get_db()
    try:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            return {"ok": True}
        sets = ", ".join(f"{k}=?" for k in fields)
        db.execute(f"UPDATE users SET {sets} WHERE id=?", (*fields.values(), current["sub"]))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id=?", (current["sub"],)).fetchone()
        return _safe_user(dict(user))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Admin — User management
# ---------------------------------------------------------------------------

@router.get("/admin/users")
def admin_list_users(skip: int = 0, limit: int = 50, admin=Depends(auth.require_admin)):
    db = auth.get_db()
    try:
        rows = db.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, skip)
        ).fetchall()
        total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return {"users": [_safe_user(dict(r)) for r in rows], "total": total}
    finally:
        db.close()


@router.put("/admin/users/{uid}")
def admin_update_user(uid: int, body: UpdateUserBody, admin=Depends(auth.require_admin)):
    db = auth.get_db()
    try:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(400, "Nothing to update")
        sets = ", ".join(f"{k}=?" for k in fields)
        db.execute(f"UPDATE users SET {sets} WHERE id=?", (*fields.values(), uid))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return _safe_user(dict(user)) if user else HTTPException(404, "Not found")
    finally:
        db.close()


@router.delete("/admin/users/{uid}", status_code=204)
def admin_delete_user(uid: int, admin=Depends(auth.require_admin)):
    db = auth.get_db()
    try:
        if uid == admin["sub"]:
            raise HTTPException(400, "Cannot delete yourself")
        db.execute("DELETE FROM users WHERE id=?", (uid,))
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Admin — Course management (SQLite-backed courses, separate from CSV KB)
# ---------------------------------------------------------------------------

@router.get("/admin/courses")
def admin_list_courses(skip: int = 0, limit: int = 50, admin=Depends(auth.require_admin)):
    db = auth.get_db()
    try:
        rows = db.execute(
            "SELECT * FROM admin_courses ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, skip)
        ).fetchall()
        total = db.execute("SELECT COUNT(*) FROM admin_courses").fetchone()[0]
        return {"courses": [_serialize_course(dict(r)) for r in rows], "total": total}
    finally:
        db.close()


@router.post("/admin/courses", status_code=201)
def admin_create_course(body: AdminCourseBody, admin=Depends(auth.require_admin)):
    db = auth.get_db()
    now = time.time()
    try:
        cur = db.execute(
            """INSERT INTO admin_courses
               (title, description, organization, category, difficulty, course_type,
                url, duration_weeks_min, duration_weeks_max, rating, skills,
                is_active, created_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (body.title, body.description, body.organization, body.category,
             body.difficulty, body.course_type, body.url,
             body.duration_weeks_min, body.duration_weeks_max, body.rating,
             json.dumps(body.skills), int(body.is_active),
             admin["sub"], now, now)
        )
        db.commit()
        row = db.execute("SELECT * FROM admin_courses WHERE id=?", (cur.lastrowid,)).fetchone()
        auth.log_activity(admin["sub"], "course_create", body.title)
        return _serialize_course(dict(row))
    finally:
        db.close()


@router.put("/admin/courses/{cid}")
def admin_update_course(cid: int, body: AdminCourseBody, admin=Depends(auth.require_admin)):
    db = auth.get_db()
    try:
        db.execute(
            """UPDATE admin_courses SET
               title=?, description=?, organization=?, category=?, difficulty=?,
               course_type=?, url=?, duration_weeks_min=?, duration_weeks_max=?,
               rating=?, skills=?, is_active=?, updated_at=?
               WHERE id=?""",
            (body.title, body.description, body.organization, body.category,
             body.difficulty, body.course_type, body.url,
             body.duration_weeks_min, body.duration_weeks_max, body.rating,
             json.dumps(body.skills), int(body.is_active), time.time(), cid)
        )
        db.commit()
        row = db.execute("SELECT * FROM admin_courses WHERE id=?", (cid,)).fetchone()
        if not row:
            raise HTTPException(404, "Course not found")
        auth.log_activity(admin["sub"], "course_update", str(cid))
        return _serialize_course(dict(row))
    finally:
        db.close()


@router.delete("/admin/courses/{cid}", status_code=204)
def admin_delete_course(cid: int, admin=Depends(auth.require_admin)):
    db = auth.get_db()
    try:
        db.execute("DELETE FROM admin_courses WHERE id=?", (cid,))
        db.commit()
        auth.log_activity(admin["sub"], "course_delete", str(cid))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Admin — Dashboard stats
# ---------------------------------------------------------------------------

@router.get("/admin/stats")
def admin_stats(admin=Depends(auth.require_admin)):
    db = auth.get_db()
    try:
        users_total = db.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0]
        admins_total = db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
        courses_total = db.execute("SELECT COUNT(*) FROM admin_courses").fetchone()[0]
        enrollments_total = db.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
        bookmarks_total = db.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0]
        active_today = db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM activity_log WHERE ts > ?", (time.time() - 86400,)
        ).fetchone()[0]
        recent_users = db.execute(
            "SELECT id, username, email, role, created_at, last_login FROM users ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
        recent_enroll = db.execute(
            """SELECT e.*, u.username FROM enrollments e
               JOIN users u ON e.user_id=u.id
               ORDER BY e.enrolled_at DESC LIMIT 5"""
        ).fetchall()
        return {
            "users_total": users_total,
            "admins_total": admins_total,
            "courses_total": courses_total,
            "enrollments_total": enrollments_total,
            "bookmarks_total": bookmarks_total,
            "active_today": active_today,
            "recent_users": [dict(r) for r in recent_users],
            "recent_enrollments": [dict(r) for r in recent_enroll],
        }
    finally:
        db.close()


@router.get("/admin/activity")
def admin_activity(limit: int = 50, admin=Depends(auth.require_admin)):
    db = auth.get_db()
    try:
        rows = db.execute(
            """SELECT a.*, u.username FROM activity_log a
               LEFT JOIN users u ON a.user_id=u.id
               ORDER BY a.ts DESC LIMIT ?""", (limit,)
        ).fetchall()
        return {"activity": [dict(r) for r in rows]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# User — Enrollments & Bookmarks
# ---------------------------------------------------------------------------

@router.post("/user/enroll")
def enroll(body: EnrollBody, current=Depends(auth.get_current_user)):
    db = auth.get_db()
    try:
        try:
            db.execute(
                "INSERT INTO enrollments (user_id, course_id, source, enrolled_at) VALUES (?,?,?,?)",
                (current["sub"], body.course_id, body.source, time.time())
            )
            db.commit()
        except sqlite3.IntegrityError:
            pass  # already enrolled
        return {"ok": True}
    finally:
        db.close()


def _enrich_course(course_id: str) -> dict:
    try:
        import main
        kb = getattr(main, "kb", None)
        if kb is not None and course_id in getattr(kb, "idx", {}):
            c = kb.df.iloc[kb.idx[course_id]]
            r = getattr(c, "rating", None)
            u = getattr(c, "url", None)
            d = getattr(c, "duration_label", None)
            return {
                "course_id": course_id,
                "title": str(c.title),
                "organization": str(c.organization),
                "category": str(c.category),
                "difficulty": str(c.difficulty),
                "rating": float(r) if (r is not None and str(r) != "nan") else None,
                "url": str(u) if (u is not None and str(u) != "nan") else None,
                "duration": str(d) if (d is not None and str(d) != "nan") else None,
            }
    except Exception:
        pass
    return {
        "course_id": course_id,
        "title": course_id,
        "organization": "Course Catalog",
        "category": "General",
        "difficulty": "Beginner",
        "rating": None,
        "url": None,
        "duration": None,
    }


@router.get("/user/enrollments")
def get_enrollments(current=Depends(auth.get_current_user)):
    db = auth.get_db()
    try:
        rows = db.execute(
            "SELECT * FROM enrollments WHERE user_id=? ORDER BY enrolled_at DESC", (current["sub"],)
        ).fetchall()
        enrollments = []
        for r in rows:
            d = dict(r)
            d["course_meta"] = _enrich_course(d["course_id"])
            enrollments.append(d)
        return {"enrollments": enrollments}
    finally:
        db.close()


@router.put("/user/enrollments/{eid}/progress")
def update_progress(eid: int, progress: int, current=Depends(auth.get_current_user)):
    db = auth.get_db()
    try:
        completed_at = time.time() if progress >= 100 else None
        db.execute(
            "UPDATE enrollments SET progress=?, completed_at=? WHERE id=? AND user_id=?",
            (min(100, max(0, progress)), completed_at, eid, current["sub"])
        )
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/user/bookmark")
def bookmark(body: BookmarkBody, current=Depends(auth.get_current_user)):
    db = auth.get_db()
    try:
        if body.action == "remove":
            db.execute("DELETE FROM bookmarks WHERE user_id=? AND course_id=?",
                       (current["sub"], body.course_id))
        else:
            try:
                db.execute(
                    "INSERT INTO bookmarks (user_id, course_id, source, created_at) VALUES (?,?,?,?)",
                    (current["sub"], body.course_id, body.source, time.time())
                )
            except sqlite3.IntegrityError:
                pass
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.get("/user/bookmarks")
def get_bookmarks(current=Depends(auth.get_current_user)):
    db = auth.get_db()
    try:
        rows = db.execute(
            "SELECT * FROM bookmarks WHERE user_id=? ORDER BY created_at DESC", (current["sub"],)
        ).fetchall()
        bookmarks = []
        for r in rows:
            d = dict(r)
            d["course_meta"] = _enrich_course(d["course_id"])
            bookmarks.append(d)
        return {"bookmarks": bookmarks}
    finally:
        db.close()


@router.get("/user/history")
def get_search_history(current=Depends(auth.get_current_user)):
    db = auth.get_db()
    try:
        rows = db.execute(
            "SELECT id, detail, ts FROM activity_log WHERE user_id=? AND action IN ('search', 'plan') ORDER BY ts DESC LIMIT 30",
            (current["sub"],)
        ).fetchall()
        seen = set()
        history = []
        for r in rows:
            q = (r["detail"] or "").strip()
            if q and q not in seen:
                seen.add(q)
                history.append({"id": r["id"], "query": q, "ts": r["ts"]})
        return {"history": history[:10]}
    finally:
        db.close()


@router.delete("/user/history")
def clear_search_history(current=Depends(auth.get_current_user)):
    db = auth.get_db()
    try:
        db.execute("DELETE FROM activity_log WHERE user_id=? AND action IN ('search', 'plan')", (current["sub"],))
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_user(u: dict) -> dict:
    u.pop("password_hash", None)
    return u


def _serialize_course(c: dict) -> dict:
    try:
        c["skills"] = json.loads(c.get("skills", "[]"))
    except Exception:
        c["skills"] = []
    return c
