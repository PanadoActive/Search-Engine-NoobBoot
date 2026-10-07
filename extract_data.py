"""Read and search the document catalog from the command line.

data.csv is produced by ingest.py. This script reads it back and searches the
full text of every document (via search_index.db).

Usage:
  python extract_data.py                       # catalog overview
  python extract_data.py budget report         # search
  python extract_data.py "exact phrase" type:pdf
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

import searchlib
from config import CSV_FILE


def extract_data(path=CSV_FILE):
    """Return the catalog rows (list of dicts). Raises FileNotFoundError if ingest.py hasn't run."""
    if not Path(path).exists():
        raise FileNotFoundError(f"Could not find '{path}'. Run ingest.py first.")
    return searchlib.load_catalog(path)


def summarize(rows):
    """Print a short summary of the catalog."""
    if not rows:
        print("No documents found. Add files to information/ and run ingest.py.")
        return
    headers = [h for h in rows[0] if not h.startswith("_")]
    print(f"Columns ({len(headers)}): {', '.join(headers)}")
    print(f"Documents: {len(rows)}")
    print("-" * 40)
    print("Count by document type:")
    for doc_type, count in sorted(collections.Counter(r.get("doc_type", "Unknown") for r in rows).items()):
        print(f"  {doc_type}: {count}")
    if not searchlib.index_available():
        print("\nNo full-text index yet - run: python ingest.py")


def search(rows, query, limit=20):
    """Ranked full-text search; returns catalog rows with _score and _snippet."""
    return searchlib.search_documents(rows, query, limit)


def main():
    rows = extract_data()
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        hits = search(rows, query)
        print(f"Search '{query}': {len(hits)} match(es)")
        for r in hits:
            print(f"  [{r['doc_type']}] {r['file_name']}  (score {r['_score']:.2f})")
            print(f"      {r['_snippet'] or r.get('summary', '')}")
            if r.get("keywords"):
                print(f"      keywords: {r['keywords']}")
        return
    summarize(rows)


if __name__ == "__main__":
    main()
