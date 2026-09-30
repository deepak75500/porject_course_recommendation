"""Crawl4AI ingestion: scrape course pages -> structured rows -> data/scraped_courses.csv.
CLI:  python scraper.py <url> [<url> ...]   (restart the API afterwards, or use POST /scrape which reloads live)"""
import asyncio, hashlib, json, re, sys
import pandas as pd
import llm
from kb import D, KB

OUT = D / "scraped_courses.csv"
LEVEL = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}


async def scrape_courses(urls, kb):
    from crawl4ai import AsyncWebCrawler  # imported lazily so the API runs without crawl4ai installed
    rows = []
    async with AsyncWebCrawler() as crawler:
        for u in urls:
            res = await crawler.arun(url=u)
            if not res.success:
                continue
            text, meta = str(res.markdown), (res.metadata or {})
            info = await asyncio.to_thread(llm.extract_course, text) or {}
            title = info.get("title") or meta.get("title") or u
            desc = info.get("description") or meta.get("description") or text[:600]
            head = f"{title} {desc} {text[:3000]}".lower()
            skills = sorted({s.lower() for s in info.get("skills", [])}) or \
                sorted(s for s in kb.vocab if re.search(rf"\b{re.escape(s)}\b", head))
            diff = info.get("difficulty") if info.get("difficulty") in LEVEL else "Beginner"
            top = kb.search(f"{title} {desc}", k=1)
            rows.append({
                "course_id": "s" + hashlib.md5(u.encode()).hexdigest()[:6], "title": title,
                "organization": info.get("organization") or "Web", "difficulty": diff, "level_rank": LEVEL[diff],
                "course_type": "Course", "url": u, "skills": json.dumps(skills),
                "category": top[0]["category"] if top else "Other", "description": desc,
                "description_status": "scraped", "summary": desc[:200],
            })
    if rows:
        new = pd.DataFrame(rows)
        old = pd.read_csv(OUT) if OUT.exists() else new.iloc[:0]
        pd.concat([old, new]).drop_duplicates("course_id", keep="last").to_csv(OUT, index=False)
    return rows


if __name__ == "__main__":
    print(json.dumps(asyncio.run(scrape_courses(sys.argv[1:], KB())), indent=2)[:2000])
