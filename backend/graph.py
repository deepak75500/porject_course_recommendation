"""LangGraph agent:  analyze -> retrieve -> (weak? rewrite -> retrieve) -> skill_gap -> path -> (gap left? widen -> path) -> narrate.
Every node appends to `trace`, which the UI shows as the agent's reasoning steps."""
import operator, re
from typing import Annotated, Any, TypedDict
from langgraph.graph import END, START, StateGraph
import llm, planner


class S(TypedDict, total=False):
    goal: str; known_terms: list; filters: dict; k: int          # inputs
    query: str; hits: list; tries: int; widen: bool              # working state
    known: set; target: list; gap: list; path: list; uncovered: list
    summary: str; used_llm: bool; relaxed: list; level: str
    is_refusal: bool
    trace: Annotated[list, operator.add]                         # append-only step log


def _regex_known(text):
    m = re.search(r"\b(?:i know|i have|i(?:'m| am) familiar with|experience (?:in|with))\s+(.+?)(?:[.?!]|,? (?:what|which|how|and (?:i )?want|now)\b|$)", text, re.I)
    return [x.strip() for x in re.split(r",|\band\b", m.group(1)) if x.strip()] if m else []


def _level(text):
    """Learning level implied by the wording: 'beginner' (from the basics), 'all' (beginner to advanced), or ''."""
    t = text.lower()
    basic = re.search(r"\b(basics?|beginner|from scratch|from the start|new to|no experience)\b", t)
    adv = re.search(r"\badvanced\b", t)
    return "all" if basic and adv else "beginner" if basic else ""


def build_graph(kb):
    def guardrail(s):
        check = llm.check_guardrail(s["goal"])
        if not check.get("is_relevant", True):
            reason = check.get("reason") or "I am specialized exclusively in educational course discovery, curriculum roadmaps, and skill-gap analysis. Please ask a question related to learning goals, subjects, or online courses."
            return {
                "is_refusal": True,
                "hits": [], "known": set(), "target": [], "gap": [], "path": [], "uncovered": [],
                "summary": "[Out of Scope] " + reason,
                "used_llm": False,
                "trace": [f"guardrail: query flagged as out-of-domain ({reason[:60]}...)"]
            }
        return {"is_refusal": False, "trace": ["guardrail: query verified as educational / course-related"]}

    def after_guardrail(s):
        return "refuse" if s.get("is_refusal") else "analyze"

    def refuse(s):
        return s

    def analyze(s):
        intent = llm.parse_intent(s["goal"]) if llm.enabled() else None
        found = (intent or {}).get("known_skills") or _regex_known(s["goal"])
        known = sorted({*s.get("known_terms", []), *found})
        return {"query": (intent or {}).get("goal") or s["goal"], "known_terms": known, "tries": 0, "level": _level(s["goal"]),
                "trace": [f"analyze: skills you already have: {known or 'none stated'}; level: "
                          f"{ {'beginner': 'from the basics', 'all': 'beginner to advanced'}.get(_level(s['goal']), 'not stated') }"]}

    def retrieve(s):
        hits = kb.search(s["query"], s["filters"], s["k"])
        return {"hits": hits, "tries": s["tries"] + 1,
                "trace": [f"retrieve: {len(hits)} courses for '{s['query']}'"]}

    def weak(s):
        cats = {h["category"] for h in s["hits"][:5]}
        return len(s["hits"]) < 3 or len(cats) >= 4  # too few, or scattered across unrelated areas

    def after_retrieve(s):
        return "rewrite" if weak(s) and s["tries"] < 3 else "skill_gap"

    def rewrite(s):
        """Self-correction: reformulate with Groq and/or relax the filters that starved the search."""
        f, note = dict(s["filters"]), []
        soft, hard = ("max_weeks", "min_rating"), ("difficulty", "category", "course_type")
        for keys in (soft, hard) if s["tries"] == 1 else (soft + hard,):  # relax soft limits first, hard ones only if that changed nothing
            note = [k for k in keys if f.get(k)]
            if note:
                break
        for k in note:
            f[k] = None
        q = (llm.rewrite_query(s["goal"], [h["title"] for h in s["hits"][:5]]) if llm.enabled() else None) or s["query"]
        if not note and q == s["query"]:
            return {"tries": 99, "trace": ["rewrite: nothing left to change, keeping current results"]}
        return {"query": q, "filters": f, "relaxed": [*s.get("relaxed", []), *note], "trace": [f"rewrite: results were weak -> query '{q}', relaxed filters: {note or 'none'}"]}

    def skill_gap(s):
        known = planner.normalise(kb, s["known_terms"])
        target = planner.target_skills(kb, s["goal"], s["hits"])
        gap = [t for t in target if not planner.covered(kb, t, known)]
        return {"known": known, "target": target, "gap": gap,
                "trace": [f"skill_gap: {len(target)} target skills, {len(gap)} missing"]}

    def path(s):
        mask = kb.mask(s["filters"])
        if not s.get("widen"):  # first pass stays on the topic of the best matches
            mask = mask & kb.df.category.isin([h["category"] for h in s["hits"][:3]]).values
        if s.get("level") == "beginner":  # "from the basics": keep advanced courses out of the path
            mask = mask & (kb.df.difficulty != "Advanced").values
        if s.get("level") == "all":  # "beginner to advanced": take up to 2 courses from each level tier
            p = []
            for diff in (["Beginner"], ["Intermediate", "Mixed"], ["Advanced"]):
                sub, _ = planner.build_path(kb, s["target"], s["known"], mask & kb.df.difficulty.isin(diff).values, max_courses=2)
                p += [c for c in sub if c["course_id"] not in {x["course_id"] for x in p}]
            for i, c in enumerate(p, 1):
                c["step"] = i
            unc = [x for x in s["gap"] if not any(x in kb.df.sk.iat[kb.idx[c["course_id"]]] for c in p)]
        else:
            p, unc = planner.build_path(kb, s["gap"], s["known"], mask)
        return {"path": p, "uncovered": unc,
                "trace": [f"path: {len(p)} courses, {len(s['gap']) - len(unc)}/{len(s['gap'])} gap skills covered"
                          + (" (all categories)" if s.get("widen") else "")]}

    def after_path(s):
        return "widen" if s["uncovered"] and not s.get("widen") else "narrate"

    def widen(s):
        return {"widen": True, "trace": [f"verify: {len(s['uncovered'])} skills uncovered -> searching all categories"]}

    def narrate(s):
        path_ = s["path"]
        ok = all({p["course_id"] for p in c["prerequisites"]} <= {x["course_id"] for x in path_[:i]} for i, c in enumerate(path_))
        n = llm.narrate(s["goal"], sorted(s["known"]), s["gap"], path_) if (llm.enabled() and path_) else None
        gap, unc = s["gap"], s["uncovered"]

        for p in path_:
            if n and p["course_id"] in (n.get("reasons") or {}):
                p["reason"] = n["reasons"][p["course_id"]]
            else:
                skills_str = ", ".join(p.get("fills", [])[:4])
                kind_str = "Prerequisite course" if p.get("kind") == "prerequisite" else f"{p.get('stage', 'Core')} course"
                p["reason"] = f"{kind_str} ({p.get('difficulty', 'Intermediate')}) covering target skills: {skills_str or 'foundational knowledge'}."

        if n and (n.get("summary")):
            summary = n["summary"]
        else:
            if not s["hits"]:
                summary = "No courses directly matched your goal and filters."
            elif not gap:
                summary = "You already possess the core skills identified for this learning goal. Recommended exploratory courses below."
            else:
                covered_cnt = len(gap) - len(unc)
                stages = [p["stage"] for p in path_ if "stage" in p]
                progression = f" from {stages[0]} to {stages[-1]}" if len(stages) > 1 and stages[0] != stages[-1] else ""
                summary = f"Identified {len(gap)} key skill(s) for your goal. Generated an ordered {len(path_)}-step learning path{progression} covering {covered_cnt}/{len(gap)} missing skills."

        if s.get("relaxed"):
            summary = f"Few results with strict filters, so I relaxed: {', '.join(s['relaxed'])}. " + summary
        return {"summary": summary, "used_llm": bool(n),
                "trace": [f"verify: prerequisite order {'valid' if ok else 'INVALID'}", f"narrate: {'Groq' if n else 'rule-based'} explanation"]}

    g = StateGraph(S)
    for name, fn in [("guardrail", guardrail), ("refuse", refuse), ("analyze", analyze), ("retrieve", retrieve),
                     ("rewrite", rewrite), ("skill_gap", skill_gap), ("path", path), ("widen", widen), ("narrate", narrate)]:
        g.add_node(name, fn)
    g.add_edge(START, "guardrail")
    g.add_conditional_edges("guardrail", after_guardrail, ["refuse", "analyze"])
    g.add_edge("refuse", END)
    g.add_edge("analyze", "retrieve")
    g.add_conditional_edges("retrieve", after_retrieve, ["rewrite", "skill_gap"])
    g.add_edge("rewrite", "retrieve"); g.add_edge("skill_gap", "path")
    g.add_conditional_edges("path", after_path, ["widen", "narrate"])
    g.add_edge("widen", "path"); g.add_edge("narrate", END)
    return g.compile()


def run(app, goal, known_terms=(), filters=None, k=8) -> dict[str, Any]:
    s = app.invoke({"goal": goal, "known_terms": list(known_terms), "filters": filters or {}, "k": k, "trace": []})
    return {
        "hits": s.get("hits", []),
        "target_skills": s.get("target", []),
        "known_skills": sorted(s.get("known", set())),
        "gap_skills": s.get("gap", []),
        "uncovered": s.get("uncovered", []),
        "path": s.get("path", []),
        "summary": s.get("summary", ""),
        "llm": s.get("used_llm", False),
        "relaxed": s.get("relaxed", []),
        "trace": s.get("trace", []),
        "is_refusal": s.get("is_refusal", False),
    }
