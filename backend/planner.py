"""Skill-gap analysis and prerequisite-aware learning path."""
import collections, math, re
import numpy as np
import llm

STAGE = {1: "Foundation", 2: "Intermediate", 3: "Advanced"}


def normalise(kb, terms):
    """Map free-text skills ('python', 'SQL') onto catalog skills."""
    out = set()
    for t in (x.strip().lower() for x in terms):
        if not t:
            continue
        if t in kb.vocab:
            out.add(t)
            continue
        found = {s for s in kb.vocab if re.search(rf"\b{re.escape(t)}\b", s)}
        out |= found or kb.similar_skills(t)  # whole-word match first, then embedding similarity ('pandas' -> data analysis)
    return out


def covered(kb, skill, known, thr=0.88):
    """A target skill counts as known if a known skill is a near-synonym (embedding cosine >= thr)."""
    return skill in known or any(kb.skill_sim(skill, k) >= thr for k in known if k in kb.vocab)


def target_skills(kb, goal, hits):
    """Rank skills of the top hits by rank-weighted IDF, then let Groq choose (or take the top 10)."""
    w, n = collections.Counter(), len(kb.df)
    for i, h in enumerate(hits[:8]):
        for s in h["skills"]:
            w[s] += math.log(n / kb.skill_df[s]) / (1 + i)
    cand = [s for s, _ in w.most_common(25)]
    return (llm.pick_target(goal, cand) if llm.enabled() else None) or cand[:10]


def build_path(kb, gap, known, mask, max_courses=5):
    df, remaining, chosen = kb.df, set(gap), {}
    # 1) greedy set cover: the course that closes the most remaining gap skills (favouring focused, well-rated ones)
    while remaining and len(chosen) < max_courses:
        best, best_score = None, 0
        for i in np.flatnonzero(mask):
            cid = df.course_id.iat[i]
            g = len(remaining & df.sk.iat[i])
            if cid in chosen or not g:
                continue
            r = df.rating.iat[i]
            score = g + 0.5 * g / len(df.sk.iat[i]) + (0 if r != r else 0.05 * r / 5)
            if score > best_score:
                best, best_score = i, score
        if best is None:
            break
        cid = df.course_id.iat[best]
        chosen[cid] = {"fills": sorted(remaining & df.sk.iat[best]), "kind": "core"}
        remaining -= df.sk.iat[best]
    # 2) pull in one prerequisite per course when the learner doesn't already know most of its skills
    for cid in list(chosen):
        for pid, _ in kb.pre[cid][:2]:
            psk = df.sk.iat[kb.idx[pid]]
            mutual = any(x == cid for x, _ in kb.pre[pid])  # skip A<->B cycles from inferred edges
            if pid not in chosen and not mutual and mask[kb.idx[pid]] and len(psk & known) < 0.5 * len(psk):
                chosen[pid] = {"fills": sorted(psk - known)[:4], "kind": "prerequisite"}
                break

    # 3) order: never before own prerequisite; otherwise foundation -> advanced
    def rank(cid, seen=()):
        r, d = int(df.level_rank.iat[kb.idx[cid]]), 0
        for pid, _ in kb.pre[cid]:
            if pid in chosen and pid not in seen and pid != cid:
                pr, pd_ = rank(pid, seen + (cid,))
                r, d = max(r, pr), max(d, pd_ + 1)
        return r, d

    order = sorted(chosen, key=lambda c: rank(c))
    path = []
    for step, cid in enumerate(order, 1):
        card = kb.card(kb.idx[cid])
        card.update(chosen[cid], step=step, stage=STAGE[rank(cid)[0]])
        card["prerequisites"] = [p for p in card["prerequisites"] if p["course_id"] in chosen]
        path.append(card)
    return path, sorted(remaining)
