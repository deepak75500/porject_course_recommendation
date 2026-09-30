from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import graph, llm
from kb import KB
import auth, routes

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="Course Finder AI", version="2.0.0", description="AI-powered course recommendation platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Init database on startup
auth.init_db()

# Mount all auth + admin + user routes
app.include_router(routes.router, prefix="")

# Knowledge base + AI agent
kb = KB()
agent = graph.build_graph(kb)


# ---------------------------------------------------------------------------
# Pydantic models for AI endpoints
# ---------------------------------------------------------------------------

class Filters(BaseModel):
    difficulty: Optional[List[str]] = None
    category: Optional[List[str]] = None
    course_type: Optional[List[str]] = None
    max_weeks: Optional[float] = None
    min_rating: Optional[float] = None


class Query(BaseModel):
    goal: str
    known_skills: List[str] = []
    filters: Filters = Filters()
    k: int = 8


class Feedback(BaseModel):
    course_id: str
    query: str = ""
    helpful: bool


class Scrape(BaseModel):
    urls: List[str]


# ---------------------------------------------------------------------------
# Core AI endpoints
# ---------------------------------------------------------------------------

@app.get("/meta")
def meta(current=Depends(auth.optional_user)):
    d = kb.df
    return {
        "courses": len(d),
        "llm": llm.enabled(),
        "dense": kb.dense is not None,
        "rerank": kb.rerank is not None,
        "categories": sorted(d.category.unique()),
        "difficulties": ["Beginner", "Intermediate", "Advanced", "Mixed"],
        "course_types": sorted(d.course_type.unique()),
        "authenticated": current is not None,
        "user_role": current.get("role") if current else None,
    }


@app.post("/search")
def search(q: Query, current=Depends(auth.optional_user)):
    if current:
        auth.log_activity(current["sub"], "search", q.goal[:120])
    return kb.search(q.goal, q.filters.model_dump(), q.k)


_plan_cache = {}

@app.post("/plan")
def plan(q: Query, current=Depends(auth.optional_user)):
    if current:
        auth.log_activity(current["sub"], "plan", q.goal[:120])
    
    cache_key = (
        q.goal.strip().lower(),
        tuple(sorted(q.known_skills)),
        str(sorted((q.filters.model_dump() or {}).items())),
        q.k
    )
    if cache_key in _plan_cache:
        cached_res = dict(_plan_cache[cache_key])
        cached_res["cached"] = True
        return cached_res

    res = graph.run(agent, q.goal, q.known_skills, q.filters.model_dump(), q.k)
    _plan_cache[cache_key] = res
    return res


@app.get("/graph")
def graph_diagram():
    return {"mermaid": agent.get_graph().draw_mermaid()}


@app.post("/feedback")
def feedback(f: Feedback, current=Depends(auth.optional_user)):
    kb.add_feedback(f.course_id, f.query, f.helpful)
    return {"ok": True}


@app.post("/scrape")
async def scrape(s: Scrape, admin=Depends(auth.require_admin)):
    try:
        import scraper
        rows = await scraper.scrape_courses(s.urls, kb)
    except ImportError:
        raise HTTPException(501, "crawl4ai not installed: pip install crawl4ai && crawl4ai-setup")
    kb.load()
    auth.log_activity(admin["sub"], "scrape", str(len(rows)) + " courses")
    return {"added": [{"course_id": r["course_id"], "title": r["title"]} for r in rows]}


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}
