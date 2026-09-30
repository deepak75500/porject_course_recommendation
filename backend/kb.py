"""Knowledge base: load + clean CSVs, hybrid (dense + TF-IDF) retrieval, filters, feedback boost."""
import collections, hashlib, json, os, pathlib, pickle, re
import numpy as np, pandas as pd
from rank_bm25 import BM25Okapi
import llm

D = pathlib.Path(__file__).parent / "data"
FB = D / "feedback.jsonl"


EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
RERANK_MODEL = os.getenv("RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-12-v2")  # or BAAI/bge-reranker-base (bigger, better)
QPREFIX = "Represent this sentence for searching relevant passages: "
CACHE = D / ".emb_cache.pkl"
STOP = set("""a an the and or of to in on for with from into by at as is are be am i me my we you your it its this that these those
what which who how do does can could should would will want wants like need learn learning course courses take next
know dont don't don t s about start suggest path prerequisite prerequisites basic basics beginner beginners advanced intermediate
which should take next need needs some any more also just get been being have has had not but if then than so such very move become""".split())


def tok(s):
    """Lowercase, drop filler words, strip plural 's' so 'analytics'~'analytic', 'networks'~'network'."""
    return [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in re.findall(r"[a-z0-9+#]+", s.lower()) if w not in STOP]


class Dense:
    """Bi-encoder (fastembed/ONNX). Document vectors are cached on disk by text hash, so re-indexing is instant."""
    def __init__(self):
        from fastembed import TextEmbedding
        self.m = TextEmbedding(EMBED_MODEL)
        self.cache = pickle.loads(CACHE.read_bytes()) if CACHE.exists() else {}

    def _embed(self, texts):
        E = np.array(list(self.m.embed(texts)), dtype=np.float32)
        return E / np.linalg.norm(E, axis=1, keepdims=True)

    def docs(self, texts):
        keys = [EMBED_MODEL + hashlib.sha1(t.encode()).hexdigest() for t in texts]
        miss = [i for i, key in enumerate(keys) if key not in self.cache]
        if miss:
            for i, v in zip(miss, self._embed([texts[i] for i in miss])):
                self.cache[keys[i]] = v
            CACHE.write_bytes(pickle.dumps(self.cache))
        return np.stack([self.cache[key] for key in keys])

    def query(self, q):
        return self._embed([QPREFIX + q])[0]

    def sym(self, texts):  # short symmetric strings (skills), no instruction prefix
        return self._embed(texts)


class Reranker:
    """Cross-encoder: reads (query, course) together, far more precise than vector similarity."""
    def __init__(self):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self.m = TextCrossEncoder(RERANK_MODEL)

    def score(self, query, docs):
        return np.array(list(self.m.rerank(query, docs)), dtype=np.float32)


def _rrf(score_arrays, depth=100, k=60):
    """Reciprocal Rank Fusion: combines rankings without needing comparable score scales."""
    out = np.zeros(len(score_arrays[0]))
    for s in score_arrays:
        for pos, i in enumerate(np.argsort(-s)[:depth]):
            if s[i] > -1e8:
                out[i] += 1 / (k + pos + 1)
    return out


def _list(s):
    try:
        return json.loads(s)
    except Exception:
        return []


def _n(x):  # NaN -> None so the value is JSON-safe
    return None if pd.isna(x) else x


class KB:
    def __init__(self):
        self.fb = collections.Counter()
        if FB.exists():
            for line in FB.read_text().splitlines():
                r = json.loads(line)
                self.fb[r["course_id"]] += 1 if r["helpful"] else -1
        self.load()

    def load(self):
        df = pd.read_csv(D / "courses_clean.csv")
        if (D / "scraped_courses.csv").exists():  # rows added by the crawler
            df = pd.concat([df, pd.read_csv(D / "scraped_courses.csv")], ignore_index=True)
        flags = df[["is_localized_variant", "is_duplicate_variant"]].fillna(False).astype(bool).any(axis=1)
        flags |= df.title.str.contains(r"[ñáéíóúãç¿¡]|\b(?:en Español|en Français)\b", regex=True)  # unflagged translations
        df = df[~flags].reset_index(drop=True)  # drop translated / duplicate listings
        for c in ("description", "summary", "organization", "category", "difficulty"):
            df[c] = df[c].fillna("")
        df["level_rank"] = df["level_rank"].fillna(1).astype(int)
        df["sk"] = df["skills"].map(_list).map(set)
        df["skills_list"] = df["skills"].map(_list)
        # descriptions flagged mismatch/missing by validation are NOT trusted -> use derived summary
        trusted = df.description_status.isin(["ok", "scraped"])
        df["blurb"] = df.description.where(trusted, df.summary)
        df["text"] = (df.title + ". " + df.organization + ". " + df.category + ". " + df.difficulty
                      + ". Skills: " + df.skills_list.map(", ".join) + ". " + df.blurb)
        self.df = df
        self.idx = {c: i for i, c in enumerate(df.course_id)}
        self.skill_df = collections.Counter(s for x in df.sk for s in x)
        cat = pd.read_csv(D / "skill_catalog.csv")
        self.vocab = set(cat.skill) | set(self.skill_df)

        p = pd.read_csv(D / "prerequisites.csv").sort_values("coverage", ascending=False)
        self.pre = collections.defaultdict(list)  # course -> [(prereq_id, coverage)]
        for r in p.itertuples():
            if r.prerequisite_course_id in self.idx:
                self.pre[r.course_id].append((r.prerequisite_course_id, r.coverage))
        for c in list(self.pre):  # inferred edges can point both ways (A<->B): drop those, they can't be ordered
            self.pre[c] = [(p, cov) for p, cov in self.pre[c] if c not in {x for x, _ in self.pre.get(p, [])}]

        self.bm25 = BM25Okapi([tok(t) for t in df.text])
        self.dense = self.rerank = self.E = self.SE = None
        self.skills = sorted(self.vocab)
        if os.getenv("MODELS", "on") != "off":
            try:
                self.dense = Dense()
                self.E = self.dense.docs(df.text.tolist())
                self.SE = self.dense.sym(self.skills)  # skill embeddings for semantic skill matching
                self.sidx = {s: i for i, s in enumerate(self.skills)}
            except Exception as e:
                print("dense model unavailable -> BM25 only:", e)
                self.dense = None
            try:
                self.rerank = Reranker()
            except Exception as e:
                print("reranker unavailable -> no rerank stage:", e)

    def similar_skills(self, term, thr=float(os.getenv("SKILL_SIM", 0.8)), top=3):
        """Catalog skills semantically close to a free-text term (e.g. 'pandas' -> data analysis)."""
        if self.dense is None:
            return set()
        sims = self.SE @ self.dense.sym([term])[0]
        return {self.skills[i] for i in np.argsort(-sims)[:top] if sims[i] >= thr}

    def skill_sim(self, a, b):
        return float(self.SE[self.sidx[a]] @ self.SE[self.sidx[b]]) if self.SE is not None else 0.0

    def mask(self, f):
        df, m = self.df, np.ones(len(self.df), bool)
        f = f or {}
        if f.get("difficulty"): m &= df.difficulty.isin(f["difficulty"]).values
        if f.get("category"): m &= df.category.isin(f["category"]).values
        if f.get("course_type"): m &= df.course_type.isin(f["course_type"]).values
        if f.get("max_weeks"): m &= (df.duration_weeks_max.isna() | (df.duration_weeks_max <= f["max_weeks"])).values
        if f.get("min_rating"): m &= (df.rating.isna() | (df.rating >= f["min_rating"])).values
        return m

    def card(self, i, score=None, query=""):
        r = self.df.iloc[i]
        toks = set(re.findall(r"[a-z]{3,}", query.lower()))
        matched = [s for s in r.skills_list if toks & set(s.split())][:4]
        return {
            "course_id": r.course_id, "title": r.title, "organization": r.organization,
            "difficulty": r.difficulty, "category": r.category, "course_type": r.course_type,
            "duration": _n(r.duration_label), "rating": _n(r.rating), "url": _n(r.url),
            "skills": r.skills_list, "blurb": r.blurb[:260],
            "score": None if score is None else round(float(score), 3),
            "why": (f"Matches your goal on: {', '.join(matched)}. " if matched else "Semantically close to your goal. ")
                   + f"{r.difficulty} · {r.category}.",
            "prerequisites": [{"course_id": p, "title": self.df.title.iat[self.idx[p]]} for p, _ in self.pre[r.course_id][:3]],
        }

    def search(self, query, filters=None, k=8, mode="full", expand=True):
        """mode: bm25 | dense | hybrid (RRF) | full (RRF + cross-encoder rerank). Degrades if models are missing."""
        m = self.mask(filters)
        if not m.any():  # filters exclude everything -> caller (the agent) decides how to relax
            return []
        hyde = llm.expand(query) if (expand and llm.enabled() and mode in ("dense", "hybrid", "full")) else None
        lex = self.bm25.get_scores(tok(query + " " + (hyde or "")))
        signals = []
        if mode != "dense" or self.dense is None:
            signals.append(lex)
        if self.dense is not None and mode != "bm25":
            signals.append(self.E @ self.dense.query(hyde or query))
        signals = [np.where(m, s, -1e9) for s in signals]
        fused = _rrf(signals) if len(signals) > 1 else (signals[0] - signals[0][m].min()) * (signals[0] > -1e8)
        cand = [i for i in np.argsort(-fused)[:30] if m[i] and fused[i] > 0]
        if not cand:
            return []
        f = np.array([fused[i] for i in cand]); f = f / (f.max() or 1)
        if self.rerank is not None and mode == "full":
            r = self.rerank.score(query, [self.df.text.iat[i][:1500] for i in cand])
            r = (r - r.min()) / ((r.max() - r.min()) or 1)
            final = 0.7 * r + 0.3 * f
        else:
            final = f
        final = final + 0.03 * np.clip([self.fb[self.df.course_id.iat[i]] for i in cand], -3, 3)  # feedback personalisation
        return [self.card(cand[j], final[j], query) for j in np.argsort(-final)[:k]]

    def add_feedback(self, course_id, query, helpful):
        self.fb[course_id] += 1 if helpful else -1
        with FB.open("a") as f:
            f.write(json.dumps({"course_id": course_id, "query": query, "helpful": helpful}) + "\n")
