import re
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx

STOPWORDS = set("a an the is are was were do does did how i my me to in on of for and or it this that can you your please what where when with add agent assistant bot".split())
STOPWORDS.update("many much worth about tell give explain want know would could should will be get have has am so then also just some any one dollar dollars usd".split())
EXPANSIONS = {"add": "create getting started", "agent": "bot assistant", "broken": "troubleshoot",
              "cost": "pricing credits", "price": "pricing credits", "connect": "channels",
              "credit": "credits pricing", "credits": "pricing", "dollar": "pricing credits",
              "dollars": "pricing credits", "usd": "pricing credits"}


def allowed_url(url, base):
    target, origin = urlsplit(url), urlsplit(base)
    path = unquote(target.path)
    return (target.scheme == "https" and target.netloc == origin.netloc and not target.username
            and not target.query and "\\" not in path and ".." not in path.split("/")
            and (path == "/docs" or path.startswith("/docs/")))


def fetch_page(client, url, base):
    for _ in range(4):
        if not allowed_url(url, base):
            raise ValueError("Documentation destination is outside the allowed origin")
        with client.stream("GET", url) as response:
            if response.is_redirect:
                url = urldefrag(urljoin(url, response.headers.get("location", "")))[0]
                continue
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type", ""):
                raise ValueError("Documentation response is not HTML")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 2_000_000:
                    raise ValueError("Documentation page exceeds size limit")
            return url, BeautifulSoup(bytes(body), "html.parser")
    raise ValueError("Too many documentation redirects")


def ingest(store, base):
    if urlsplit(base).netloc != "docs.ampere.sh":
        raise ValueError("Only docs.ampere.sh is approved for documentation ingestion")
    queue, visited, passages, failures, missing = [base], set(), [], [], []
    with httpx.Client(timeout=25, follow_redirects=False, headers={"User-Agent": "AmpereAssessmentDocs/1.0"}) as client:
        while queue and len(visited) < 40:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                final_url, soup = fetch_page(client, url, base)
                for link in soup.select("a[href]"):
                    candidate = urldefrag(urljoin(final_url, link["href"]))[0].rstrip("/")
                    if allowed_url(candidate, base) and candidate not in visited and candidate not in queue:
                        queue.append(candidate)
                article = soup.select_one("article") or soup.select_one("main")
                if article is None:
                    raise ValueError("Documentation article not found")
                title = (soup.title.get_text(" ", strip=True) if soup.title else final_url)[:300]
                for element in article.select("script,style,nav,button"):
                    element.decompose()
                text = article.get_text(" ", strip=True)
                if len(text) < 80:
                    raise ValueError("Documentation article is empty")
                for start in range(0, len(text), 1400):
                    passages.append((final_url, title, text[start:start + 1700]))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (404, 410):
                    missing.append(url)
                    continue
                print(f"Documentation page failed: {url} ({type(exc).__name__})")
                failures.append(url)
            except (httpx.HTTPError, ValueError) as exc:
                print(f"Documentation page failed: {url} ({type(exc).__name__})")
                failures.append(url)
    # Preserve the last good snapshot if refresh is incomplete.
    if failures or queue or not passages:
        raise ValueError(f"Incomplete documentation refresh ({len(failures)} failed pages); previous index preserved")
    with store.connect() as db:
        db.execute("DELETE FROM passages")
        db.executemany("INSERT INTO passages(url,title,text) VALUES(?,?,?)", passages)
        db.execute("INSERT INTO passage_search(passage_search) VALUES('rebuild')")
    return {"pages": len({p[0] for p in passages}), "passages": len(passages), "missing_pages": missing}


def search(store, question, history):
    def tokens(text):
        words = re.findall(r"[a-z0-9]+", text.lower())
        expanded = words + [v for k, v in EXPANSIONS.items() if k in words]
        return list(dict.fromkeys(w for w in re.findall(r"[a-z0-9]+", " ".join(expanded))
                                  if w not in STOPWORDS and len(w) > 1))[:30]

    terms = tokens(question)
    # A short explicit topic (e.g. 'credits') must not inherit an unrelated old topic.
    if not terms or re.search(r"\b(that|it|those|there|these|them)\b", question, re.I):
        for item in reversed(history):
            if item["role"] == "user":
                terms.extend(tokens(item["content"]))
                if len(terms) >= 12:
                    break
    terms = list(dict.fromkeys(terms))[:40]
    if not terms:
        return []
    expression = " OR ".join(f'"{word}"' for word in terms)
    with store.connect() as db:
        rows = db.execute("""SELECT p.id,p.url,p.title,p.text FROM passage_search s
            JOIN passages p ON p.id=s.rowid WHERE passage_search MATCH ?
            ORDER BY bm25(passage_search,3,1) LIMIT 30""", (expression,)).fetchall()
    # A title match alone is not evidence: trailing navigation fragments often carry
    # the page title but none of the question's actual topic in their body.
    return [dict(row) for row in rows if set(re.findall(r"[a-z0-9]+", row["text"].lower())) & set(terms)][:5]

