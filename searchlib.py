"""Search core: a SQLite FTS5 full-text index (BM25 ranking) over document text,
plus helpers to load and search the data.csv catalog.

Why this exists: the original search only looked at a one-sentence summary and
eight keywords per file, so words that appear in the body of a document could
never be found. ingest.py now stores the full text here (split into passages),
and the GUI/CLI search it with proper ranking, stemming ("budgets" finds
"budget"), phrases ("exact phrase") and a type filter (type:pdf).
"""
from __future__ import annotations

import csv
import datetime
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from config import CHUNK_OVERLAP, CHUNK_WORDS, CSV_FILE, DB_FILE

STOP = frozenset("""a an the and or of to in for on with is are was were be been it its this that these
those from at by as do does did can will not but if then than so what which who whom how why when where
i you he she we they me my your our their about into over under""".split())

TYPE_ALIASES = {
    "pdf": "PDF", "excel": "Spreadsheet", "xlsx": "Spreadsheet", "xls": "Spreadsheet",
    "spreadsheet": "Spreadsheet", "word": "Document", "docx": "Document", "doc": "Document",
    "document": "Document", "image": "Image", "img": "Image", "png": "Image", "jpg": "Image",
    "text": "Text", "txt": "Text", "md": "Text", "csv": "Text",
}
_TYPE_TOKEN = re.compile(r"^(?:type|ext|filetype):(\w+)$", re.I)
_QUERY_PARTS = re.compile(r'"([^"]+)"|(\S+)')
MARK_OPEN, MARK_CLOSE = "«", "»"


# --------------------------------------------------------------------------- small helpers
def parse_dt(v):
    if not v:
        return None
    for parse in (lambda s: datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S"), datetime.datetime.fromisoformat):
        try:
            return parse(str(v))
        except ValueError:
            continue
    return None


def fmt_dt(d):
    return d.strftime("%Y-%m-%d") if d else ""


def chunk_text(text: str, size: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping word windows (passages)."""
    if not text or not text.strip():
        return []
    words = text.split()
    step = max(1, size - overlap)
    chunks, i = [], 0
    while words:
        chunks.append(" ".join(words[i:i + size]))
        if i + size >= len(words):
            break
        i += step
    return chunks


# --------------------------------------------------------------------------- query parsing
def parse_query(query: str):
    """Return (words, phrases, doc_type). doc_type comes from a `type:pdf` token."""
    words, phrases, doc_type = [], [], None
    for m in _QUERY_PARTS.finditer(query or ""):
        phrase, bare = m.groups()
        if phrase:
            parts = re.findall(r"\w+", phrase)
            if len(parts) > 1:
                phrases.append(" ".join(parts))
            else:
                words += parts
            continue
        t = _TYPE_TOKEN.match(bare)
        if t:
            key = t.group(1).lower()
            doc_type = TYPE_ALIASES.get(key, key.upper() if len(key) <= 4 else key.title())
            continue
        words += re.findall(r"\w+", bare)
    content = [w for w in words if w.lower() not in STOP]
    return (content or words), phrases, doc_type     # keep stop words if that's all there is


def build_match(words, phrases, op="AND"):
    parts = [f'"{w}"' for w in words] + [f'"{p}"' for p in phrases]
    return f" {op} ".join(parts) if parts else None


# --------------------------------------------------------------------------- index (write side)
def connect(path=DB_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS docs(rel_path TEXT PRIMARY KEY, size INTEGER, mtime TEXT)")
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5("
                 "rel_path UNINDEXED, doc_type UNINDEXED, title, body, "
                 "tokenize='porter unicode61 remove_diacritics 2')")
    return conn


def is_current(conn, rel: str, size: int, mtime: str) -> bool:
    row = conn.execute("SELECT size, mtime FROM docs WHERE rel_path=?", (rel,)).fetchone()
    return bool(row) and row[0] == size and row[1] == mtime


def store(conn, rel: str, doc_type: str, title: str, text: str, size: int, mtime: str) -> None:
    """(Re)index one document: a metadata chunk (heavily weighted) + body passages."""
    conn.execute("DELETE FROM chunks WHERE rel_path=?", (rel,))
    conn.execute("INSERT INTO chunks(rel_path, doc_type, title, body) VALUES (?,?,?,'')", (rel, doc_type, title))
    conn.executemany("INSERT INTO chunks(rel_path, doc_type, title, body) VALUES (?,?,'',?)",
                     [(rel, doc_type, c) for c in chunk_text(text)])
    conn.execute("INSERT OR REPLACE INTO docs(rel_path, size, mtime) VALUES (?,?,?)", (rel, size, mtime))
    conn.commit()


def prune(conn, keep: set[str]) -> int:
    """Drop index entries for files that no longer exist."""
    gone = [r[0] for r in conn.execute("SELECT rel_path FROM docs") if r[0] not in keep]
    for rel in gone:
        conn.execute("DELETE FROM chunks WHERE rel_path=?", (rel,))
        conn.execute("DELETE FROM docs WHERE rel_path=?", (rel,))
    conn.commit()
    return len(gone)


# --------------------------------------------------------------------------- index (read side)
def index_available(path=DB_FILE) -> bool:
    if not Path(path).exists():
        return False
    try:
        with closing(sqlite3.connect(str(path))) as conn:
            return conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0] > 0
    except sqlite3.Error:
        return False


def _run(conn, query, select, limit, extra_where=""):
    """Run the query as AND first; fall back to OR when nothing matches."""
    words, phrases, doc_type = parse_query(query)
    for op in ("AND", "OR"):
        match = build_match(words, phrases, op)
        if not match:
            return [], None, "none"
        sql = f"SELECT {select} FROM chunks WHERE chunks MATCH ? {extra_where}"
        args = [match]
        if doc_type:
            sql += " AND doc_type = ? COLLATE NOCASE"
            args.append(doc_type)
        sql += " ORDER BY rank_ LIMIT ?"
        args.append(limit)
        try:
            rows = conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            return [], doc_type, "none"
        if rows or len(words) + len(phrases) == 1:
            return rows, doc_type, "all" if op == "AND" else "any"
    return [], doc_type, "any"


def search_index(query: str, limit: int = 50, path=DB_FILE) -> list[dict]:
    """Best passage per document, ranked by BM25 (title/keywords weigh 6x the body)."""
    select = ("rel_path, doc_type, bm25(chunks, 0.0, 0.0, 6.0, 1.0) AS rank_, "
              f"snippet(chunks, 3, '{MARK_OPEN}', '{MARK_CLOSE}', ' … ', 28), "
              f"snippet(chunks, 2, '{MARK_OPEN}', '{MARK_CLOSE}', ' … ', 28)")
    with closing(sqlite3.connect(str(path))) as conn:
        rows, _, mode = _run(conn, query, select, limit * 12)
    hits, seen, extra = [], {}, {}
    for rel, dtype, rank, s_body, s_title in rows:
        if rel in seen:
            extra[rel] = extra.get(rel, 0) + 1
            continue
        snippet = next((s for s in (s_body, s_title) if MARK_OPEN in s), s_body or s_title)
        seen[rel] = {"rel_path": rel, "doc_type": dtype, "score": -rank, "snippet": snippet, "match": mode}
        hits.append(seen[rel])
    for h in hits:                                    # small bonus for documents with many matching passages
        h["score"] += 0.15 * min(extra.get(h["rel_path"], 0), 10)
    hits.sort(key=lambda h: -h["score"])
    return hits[:limit]


def passages(query: str, k: int = 6, path=DB_FILE) -> list[dict]:
    """Top body passages (max 2 per document) - the context for question answering."""
    select = "rel_path, body, bm25(chunks, 0.0, 0.0, 6.0, 1.0) AS rank_"
    with closing(sqlite3.connect(str(path))) as conn:
        rows, _, _ = _run(conn, query, select, k * 6, extra_where="AND body != ''")
    out, per_doc = [], {}
    for rel, body, _rank in rows:
        if per_doc.get(rel, 0) < 2:
            per_doc[rel] = per_doc.get(rel, 0) + 1
            out.append({"rel_path": rel, "text": body})
        if len(out) >= k:
            break
    return out


# --------------------------------------------------------------------------- catalog (data.csv)
def load_catalog(path=CSV_FILE) -> list[dict]:
    """Read data.csv into a list of dicts with a few derived fields. [] if missing."""
    if not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["_dt"] = parse_dt(r.get("modified"))
        r["_date_s"] = fmt_dt(r["_dt"])
        r["_kw_list"] = [k.strip() for k in (r.get("keywords") or "").split(",") if k.strip()]
    return rows


def _catalog_fallback(catalog, words, phrases):
    """Used only when no full-text index exists: whole-word matching on name/summary/keywords."""
    terms = [w.lower() for w in words] + [p.lower() for p in phrases]
    out = []
    for row in catalog:
        name = (row.get("file_name") or "").lower()
        summary = (row.get("summary") or "").lower()
        kws = [k.lower() for k in row["_kw_list"]]
        s = 0.0
        for t in terms:
            pat = re.compile(rf"\b{re.escape(t)}")
            s += (12 if t in kws else 6 if pat.search(" ".join(kws)) else 0)
            s += 8 if pat.search(name) else 0
            s += 4 if pat.search(summary) else 0
        if s:
            out.append((row, s))
    return out


def search_documents(catalog, query, limit=None, doc_type=None, db_path=DB_FILE):
    """Search the catalog. Empty query (or only a type: filter) lists documents, newest first.

    Returns copies of catalog rows with _score, _snippet and _match added.
    """
    words, phrases, q_type = parse_query(query)
    doc_type = doc_type or q_type
    by_path = {r.get("relative_path"): r for r in catalog}

    def keep(row):
        return not doc_type or (row.get("doc_type") or "").lower() == doc_type.lower()

    if not words and not phrases:                       # nothing to search for: browse
        rows = sorted((r for r in catalog if keep(r)), key=lambda r: r["_dt"] or datetime.datetime.min, reverse=True)
        results = [dict(r, _score=0.0, _snippet="", _match="all") for r in rows]
    elif index_available(db_path):
        results = []
        for h in search_index(query, limit=len(catalog) + 5, path=db_path):
            row = by_path.get(h["rel_path"])
            if row and keep(row):
                results.append(dict(row, _score=h["score"], _snippet=h["snippet"], _match=h["match"]))
    else:
        scored = _catalog_fallback([r for r in catalog if keep(r)], words, phrases)
        results = [dict(r, _score=s, _snippet="", _match="any") for r, s in scored]
        results.sort(key=lambda r: (-r["_score"], r.get("file_name", "")))
    return results[:limit] if limit else results
