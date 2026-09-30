"""Offline evaluation on representative student queries (no LLM needed).
Metrics: P@5 (relevant = expected category or expected keyword in title/skills), gap coverage of the path,
and prerequisite-order validity (no course listed before one of its prerequisites)."""
import graph
from kb import KB

Q = [
    ("I want to learn data science from the basics. Which courses should I start with?", {"Data Science & Analytics", "AI & Machine Learning"}, ["data"], []),
    ("I know Python and SQL. What courses should I take next to move into machine learning?", {"AI & Machine Learning", "Data Science & Analytics"}, ["machine learning"], []),
    ("I want to learn cloud computing but I don't know which prerequisite courses I need.", {"Cloud Computing"}, ["cloud"], []),
    ("Can you suggest a learning path from beginner to advanced data analytics?", {"Data Science & Analytics"}, ["analy"], []),
    ("become a cybersecurity analyst", {"Cybersecurity"}, ["security"], []),
    ("learn deep learning and neural networks", {"AI & Machine Learning"}, ["deep learning", "neural"], ["python"]),
    ("financial accounting fundamentals", {"Finance & Accounting"}, ["financ", "account"], []),
    ("UX design for beginners", {"Design & UX"}, ["design", "ux"], []),
]

def ablate(kb):
    """Mean P@5 for each retrieval stage: shows what dense / fusion / reranking actually add."""
    for mode in ("bm25", "dense", "hybrid", "full"):
        if mode in ("dense", "hybrid") and kb.dense is None or mode == "full" and kb.rerank is None:
            print(f"{mode:7s} skipped (model not loaded)")
            continue
        s = 0
        for goal, cats, kws, _ in Q:
            top = kb.search(goal, k=5, mode=mode, expand=False)
            s += sum(h["category"] in cats or any(k in (h["title"] + " ".join(h["skills"])).lower() for k in kws) for h in top) / max(len(top), 1)
        print(f"{mode:7s} mean P@5 = {s / len(Q):.3f}")
    print()


if __name__ == "__main__":
    kb, rows = KB(), []
    agent = graph.build_graph(kb)
    ablate(kb)
    for goal, cats, kws, known in Q:
        r = graph.run(agent, goal, known)
        top = r["hits"][:5]
        rel = lambda h: h["category"] in cats or any(k in (h["title"] + " ".join(h["skills"])).lower() for k in kws)
        p5 = sum(map(rel, top)) / max(len(top), 1)
        cov = 1 - len(r["uncovered"]) / max(len(r["gap_skills"]), 1)
        pos = {c["course_id"]: i for i, c in enumerate(r["path"])}
        ok = all(pos[p["course_id"]] < pos[c["course_id"]] for c in r["path"] for p in c["prerequisites"])
        rows.append((p5, cov, ok))
        print(f"P@5={p5:.2f} gapcov={cov:.2f} order_ok={ok} path={len(r['path'])}  | {goal}")
    n = len(rows)
    print(f"\nMEAN P@5={sum(r[0] for r in rows)/n:.2f}  gap coverage={sum(r[1] for r in rows)/n:.2f}  order valid={sum(r[2] for r in rows)}/{n}")
