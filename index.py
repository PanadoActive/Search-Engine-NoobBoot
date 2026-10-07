#!/usr/bin/env python3
"""
PySearch GUI (CustomTkinter) - search your LOCAL documents.

Searches the full text of every file ingested by ingest.py (search_index.db),
ranked with BM25, with matching passages shown under each result.

Search tips:
  budget report          all words (falls back to "any word" if nothing has them all)
  "exact phrase"         words next to each other
  budget type:pdf        only one document type (pdf, excel, word, image, text)

Tabs:
  Ask        : ask a question; answers are built from the best matching passages
  Documents  : ranked results; click a title to open the file
  By Type    : the same results grouped by document type
  Keywords   : the most common keywords across matching documents
  SIMPLE / ADVANCED : plain-text summaries of the results

Install:   pip install -r requirements.txt
Run:       python ingest.py     (once, and whenever files change)
           python index.py
"""
import collections
import csv
import datetime
import json
import os
import queue
import re
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import ingest
import llm
import searchlib
from searchlib import STOP
from config import BASE_DIR, CSV_FILE, INFORMATION_DIR

PREFS_FILE = BASE_DIR / ".prefs.json"


# ----------------------------------------------------------------------------- helpers
def trunc(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def human_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def tokenize(text):
    return [w for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if w not in STOP]


def top_terms(texts, exclude=(), k=8):
    c = collections.Counter(w for t in texts for w in tokenize(t) if w not in exclude)
    return [w for w, _ in c.most_common(k)]


def resolve_path(row, root=INFORMATION_DIR):
    rel = row.get("relative_path") or row.get("file_name") or ""
    return (Path(root) / rel).resolve()


def _launch(args):
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_file(row):
    """Open the document with the OS default application."""
    path = resolve_path(row)
    if not path.exists():
        return False
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            _launch(["open", str(path)])
        else:
            _launch(["xdg-open", str(path)])
        return True
    except OSError:
        return webbrowser.open(path.as_uri())


def reveal_file(row):
    """Show the document in the file manager."""
    path = resolve_path(row)
    if not path.exists():
        return False
    try:
        if sys.platform.startswith("win"):
            _launch(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            _launch(["open", "-R", str(path)])
        else:
            _launch(["xdg-open", str(path.parent)])
        return True
    except OSError:
        return False


# ----------------------------------------------------------------------------- Q&A over the documents
def answer_question(catalog, question, top_k=5):
    """Answer a question from the best matching passages.

    Returns (answer_text, sources) - sources are catalog rows, most relevant first.
    Uses an LLM when a key is configured (it sees only the retrieved passages),
    otherwise shows the matching passages themselves.
    """
    by_path = {r.get("relative_path"): r for r in catalog}
    grouped = collections.OrderedDict()                 # doc -> [passage, ...]
    if searchlib.index_available():
        for p in searchlib.passages(question, k=top_k + 1):
            if p["rel_path"] in by_path:
                grouped.setdefault(p["rel_path"], []).append(p["text"])
    if not grouped:                                     # no index: fall back to catalog summaries
        for r in searchlib.search_documents(catalog, question, limit=top_k):
            grouped[r["relative_path"]] = [r.get("summary", "")]
    if not grouped:
        return ("I couldn't find anything in your documents related to that question.\n"
                "Try different wording, or add more files and re-run ingest.py.", [])

    sources = [by_path[rel] for rel in list(grouped)[:top_k]]
    context = "\n\n".join(f"[{i}] {by_path[rel].get('file_name', '')}:\n" + "\n...\n".join(t[:900] for t in texts)
                          for i, (rel, texts) in enumerate(list(grouped.items())[:top_k], 1))
    if llm.get_client():
        answer = llm.complete(
            "Answer the question using ONLY the document excerpts below. Be concise (2-4 sentences) and cite "
            "the excerpts you used by their [number]. If they don't contain the answer, say so.\n\n"
            f"QUESTION: {question}\n\nEXCERPTS:\n{context}", max_tokens=350)
        if answer:
            return answer, sources
    lines = [f'Most relevant passages for: "{question}"', ""]
    for i, (rel, texts) in enumerate(list(grouped.items())[:top_k], 1):
        lines.append(f"[{i}] {by_path[rel].get('file_name', '')}: {trunc(texts[0], 280)}")
    lines += ["", "Open the sources below to read the full documents."]
    if llm.last_error:
        lines += ["", f"(AI answer unavailable: {llm.last_error})"]
    return "\n".join(lines), sources


# ----------------------------------------------------------------------------- SIMPLE / ADVANCED answers
def build_simple(query, results, total):
    if not results:
        if total == 0:
            return ("No catalog found.\n\n"
                    f"'{CSV_FILE.name}' is empty or missing. Add files to the '{INFORMATION_DIR.name}/' folder "
                    "and run:  python ingest.py")
        return f'No documents matched "{query}". Try a different keyword.'

    types = collections.Counter(r.get("doc_type", "Other") for r in results)
    top_type, cnt = types.most_common(1)[0]
    header = "all documents" if not query.strip() else f'"{query}"'
    lines = [f"SIMPLE ANSWER for {header}", "=" * 60, ""]
    if results[0].get("_match") == "any":
        lines += ["(No document contains every word, so these contain at least one of them.)", ""]
    for i, r in enumerate(results[:5], 1):
        lines.append(f"{i}. {r.get('file_name', '')}  ({r.get('doc_type', '')})")
        lines.append(f"   {trunc(r.get('_snippet') or r.get('summary', ''), 160)}")
        if r.get("_kw_list"):
            lines.append(f"   keywords: {', '.join(r['_kw_list'][:6])}")
    lines += ["", f"Quick take: {len(results)} matching document(s); most are '{top_type}' ({cnt}). "
                  "Open #1 to start, or switch to the 'By Type' and 'Keywords' tabs to explore."]
    return "\n".join(lines)


def build_advanced(query, results, total):
    if not results:
        return build_simple(query, results, total)
    header = "all documents" if not query.strip() else f'"{query}"'
    groups = collections.defaultdict(list)
    for r in results:
        groups[r.get("doc_type", "Other")].append(r)

    L = [f"ADVANCED ANSWER for {header}", "=" * 60, "", "DOCUMENTS BY TYPE", "-" * 60]
    for t, xs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        themes = ", ".join(top_terms([f"{x.get('summary', '')} {x.get('keywords', '')}" for x in xs])) or "n/a"
        L.append(f"\n## {t}  ({len(xs)} document(s)) - recurring terms: {themes}")
        for x in xs[:4]:
            L.append(f"  • {x.get('file_name', '')}  [{human_size(x.get('size_bytes'))}"
                     f"{' · ' + x['_date_s'] if x.get('_date_s') else ''}]")
            L.append(f"    {trunc(x.get('_snippet') or x.get('summary', ''), 200)}")
            if x.get("_kw_list"):
                L.append(f"    keywords: {', '.join(x['_kw_list'][:8])}")

    kw_counter = collections.Counter(k.lower() for r in results for k in r.get("_kw_list", []))
    L += ["", "TOP KEYWORDS ACROSS MATCHES", "-" * 60,
          ", ".join(f"{k} ({c})" for k, c in kw_counter.most_common(15)) or
          "No keywords recorded. Re-run: python ingest.py --rebuild"]

    dated = [r for r in results if r.get("_dt")]
    L += ["", "CATALOG FACTS", "-" * 60, f"Matching documents: {len(results)} of {total} in catalog"]
    if dated:
        newest, oldest = max(dated, key=lambda r: r["_dt"]), min(dated, key=lambda r: r["_dt"])
        L += [f"Newest: {newest.get('file_name', '')} ({newest['_date_s']})",
              f"Oldest: {oldest.get('file_name', '')} ({oldest['_date_s']})"]
    sizes = []
    for r in results:
        try:
            sizes.append(float(r["size_bytes"]))
        except (KeyError, TypeError, ValueError):
            pass
    if sizes:
        L.append(f"Total size: {human_size(sum(sizes))} · largest {human_size(max(sizes))}")
    return "\n".join(L)


# ----------------------------------------------------------------------------- GUI (CustomTkinter)
# Colours are (light_mode, dark_mode) tuples so contrast holds in both themes.
LINK = ("#1a0dab", "#8ab4f8")
PATH_GREEN = ("#1a7f37", "#81c995")
MUTED = ("#5f6368", "#9aa0a6")
BODY = ("#1f1f1f", "#e8eaed")
WRAP = 880


def hand(widget):
    for target in (widget, getattr(widget, "_label", None), getattr(widget, "_canvas", None)):
        if target is not None:
            try:
                target.configure(cursor="hand2")
            except Exception:  # noqa: BLE001 - cosmetic only; private attrs may change between versions
                pass


def clickable(parent, text, callback, size=15, color=LINK):
    lb = ctk.CTkLabel(parent, text=text, text_color=color, anchor="w", justify="left", wraplength=WRAP,
                      font=ctk.CTkFont(size=size, underline=True))
    lb.bind("<Button-1>", lambda e: callback())
    hand(lb)
    return lb


def label(parent, text, size=13, color=None, bold=False, wrap=WRAP, **kw):
    return ctk.CTkLabel(parent, text=text, text_color=color or BODY, anchor="w", justify="left", wraplength=wrap,
                        font=ctk.CTkFont(size=size, weight="bold" if bold else "normal"), **kw)


def clear(frame):
    for w in frame.winfo_children():
        w.destroy()


class App:
    ALL_TYPES = "All types"

    def __init__(self, root):
        self.root = root
        root.title("PySearch - local document search")
        root.geometry("1150x800")
        root.minsize(800, 500)
        self.q = queue.Queue()
        self._seq = 0                       # lets us ignore results from an older, slower search
        self._after = None
        self._last_results = []             # most recently rendered results (for CSV export)
        self._from_year = None              # active date filter lower bound
        self._to_year = None                # active date filter upper bound
        self.catalog = searchlib.load_catalog()

        # --- top bar
        top = ctk.CTkFrame(root, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 4))
        self.entry = ctk.CTkEntry(top, height=40, font=ctk.CTkFont(size=16),
                                  placeholder_text='Search inside your documents…  ("exact phrase", type:pdf)')
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self.start())
        self.type_var = ctk.StringVar(value=self.ALL_TYPES)
        self.type_menu = ctk.CTkOptionMenu(top, values=[self.ALL_TYPES], variable=self.type_var, width=130, height=40)
        self.type_menu.pack(side="left", padx=(12, 0))
        self.sort_var = ctk.StringVar(value="Relevance")
        ctk.CTkLabel(top, text="Sort:").pack(side="left", padx=(12, 4))
        ctk.CTkOptionMenu(top, values=["Relevance", "Newest", "Oldest", "Name A\u2192Z", "Name Z\u2192A"],
                          variable=self.sort_var, width=130, height=40).pack(side="left")
        # --- date range filter
        ctk.CTkLabel(top, text="From:").pack(side="left", padx=(12, 4))
        self.from_year_entry = ctk.CTkEntry(top, width=70, height=40, placeholder_text="YYYY")
        self.from_year_entry.pack(side="left")
        ctk.CTkLabel(top, text="To:").pack(side="left", padx=(6, 4))
        self.to_year_entry = ctk.CTkEntry(top, width=70, height=40, placeholder_text="YYYY")
        self.to_year_entry.pack(side="left")
        ctk.CTkLabel(top, text="Max:").pack(side="left", padx=(12, 4))
        self.n = ctk.StringVar(value="50")
        ctk.CTkOptionMenu(top, values=["10", "25", "50", "100", "All"], variable=self.n, width=80,
                          height=40).pack(side="left")
        ctk.CTkButton(top, text="Search", width=100, height=40, command=self.start,
                      font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=(12, 0))
        ctk.CTkButton(top, text="Reload", width=90, height=40, command=self.reload).pack(side="left", padx=(8, 0))
        ctk.CTkButton(top, text="Export CSV", width=100, height=40, command=self.export_csv).pack(side="left", padx=(8, 0))
        self.reindex_btn = ctk.CTkButton(top, text="Re-index", width=90, height=40, command=self.reindex)
        self.reindex_btn.pack(side="left", padx=(8, 0))
        # Load saved theme preference
        _prefs = {}
        try:
            with open(PREFS_FILE, encoding="utf-8") as _f:
                _prefs = json.load(_f)
        except Exception:
            pass
        self.is_dark = bool(_prefs.get("dark_mode", False))
        ctk.set_appearance_mode("Dark" if self.is_dark else "Light")
        self.theme_btn = ctk.CTkButton(top, text="Light mode" if self.is_dark else "Dark mode", width=110, height=40, command=self.toggle_theme)
        self.theme_btn.pack(side="left", padx=(14, 0))

        self.progress_bar = ctk.CTkProgressBar(root, width=400, mode="indeterminate")
        self.progress_bar.pack(padx=16, pady=(2, 0))
        self.progress_bar.pack_forget()  # hide initially

        self.status = ctk.CTkLabel(root, text="", anchor="w", text_color=MUTED)
        self.status.pack(fill="x", padx=16)

        # --- tabs
        self.tabs = ctk.CTkTabview(root)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.frames, self.texts = {}, {}

        ask_tab = self.tabs.add("Ask")
        ask_bar = ctk.CTkFrame(ask_tab, fg_color="transparent")
        ask_bar.pack(fill="x", padx=4, pady=(4, 6))
        self.ask_entry = ctk.CTkEntry(ask_bar, height=38, font=ctk.CTkFont(size=15),
                                      placeholder_text="Ask a question about your documents…")
        self.ask_entry.pack(side="left", fill="x", expand=True)
        self.ask_entry.bind("<Return>", lambda e: self.ask())
        ctk.CTkButton(ask_bar, text="Ask", width=90, height=38, command=self.ask,
                      font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=(8, 0))
        self.answer_box = ctk.CTkTextbox(ask_tab, wrap="word", height=200, font=ctk.CTkFont(size=14))
        self.answer_box.pack(fill="x", padx=4, pady=(0, 6))
        self.answer_box.configure(state="disabled")
        label(ask_tab, "Sources", 14, bold=True).pack(anchor="w", padx=6, pady=(2, 0))
        self.ask_sources = ctk.CTkScrollableFrame(ask_tab, fg_color="transparent")
        self.ask_sources.pack(fill="both", expand=True, padx=2)

        for name in ("Documents", "By Type", "Keywords"):
            f = ctk.CTkScrollableFrame(self.tabs.add(name), fg_color="transparent")
            f.pack(fill="both", expand=True)
            self.frames[name] = f
        for name in ("SIMPLE", "ADVANCED"):
            t = ctk.CTkTextbox(self.tabs.add(name), wrap="word", font=ctk.CTkFont(family="Consolas", size=13))
            t.pack(fill="both", expand=True)
            t.configure(state="disabled")
            self.texts[name] = t
        self.tabs.set("Documents")

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll()
        self._refresh_types()
        if not self.catalog:
            self.status.configure(text=f"No catalog loaded. Add files to '{INFORMATION_DIR.name}/' and run: python ingest.py")
        else:
            note = "" if searchlib.index_available() else "  (no full-text index yet - run: python ingest.py)"
            self.status.configure(text=f"{len(self.catalog)} documents in catalog.{note}")
            self.render("", self._apply_sort(searchlib.search_documents(self.catalog, "", self._limit())))

    # --- plumbing
    def toggle_theme(self):
        self.is_dark = not self.is_dark
        ctk.set_appearance_mode("Dark" if self.is_dark else "Light")
        self.theme_btn.configure(text="Light mode" if self.is_dark else "Dark mode")
        try:
            with open(PREFS_FILE, "w", encoding="utf-8") as _f:
                json.dump({"dark_mode": self.is_dark}, _f)
        except Exception:
            pass

    def _apply_sort(self, results):
        sort = self.sort_var.get()
        if sort == "Newest":
            return sorted(results, key=lambda r: r.get("_dt") or datetime.datetime.min, reverse=True)
        if sort == "Oldest":
            return sorted(results, key=lambda r: r.get("_dt") or datetime.datetime.min)
        if sort == "Name A\u2192Z":
            return sorted(results, key=lambda r: (r.get("file_name") or "").lower())
        if sort == "Name Z\u2192A":
            return sorted(results, key=lambda r: (r.get("file_name") or "").lower(), reverse=True)
        return results  # Relevance: leave as-is

    def _apply_date_filter(self, results, from_year, to_year):
        """Keep rows whose _dt is None (unknown) or whose year falls within [from_year, to_year]."""
        if from_year is None and to_year is None:
            return results
        filtered = []
        for r in results:
            dt = r.get("_dt")
            if dt is None:
                filtered.append(r)  # unknown date: never exclude
            else:
                if from_year is not None and dt.year < from_year:
                    continue
                if to_year is not None and dt.year > to_year:
                    continue
                filtered.append(r)
        return filtered

    def export_csv(self):
        """Export the most recently rendered results to a CSV file chosen by the user."""
        if not self._last_results:
            self.status.configure(text="Nothing to export yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="search_results.csv",
            title="Save results as CSV",
        )
        if not path:
            return  # user cancelled
        # Columns to export — skip internal datetime objects (_dt); keep other underscored fields
        export_cols = ["file_name", "doc_type", "size_bytes", "modified", "summary",
                       "keywords", "relative_path", "_score", "_snippet"]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=export_cols, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(self._last_results)
            fname = Path(path).name
            self.status.configure(text=f"Exported {len(self._last_results)} results to {fname}")
        except Exception as exc:  # noqa: BLE001
            self.status.configure(text=f"Export failed: {exc}")

    def _ingest_log(self, msg):
        """Called by ingest.ingest() on each file; posts status updates to the GUI queue."""
        self.q.put(lambda m=msg: self.status.configure(text=f"Re-indexing: {m}"))

    def reindex(self):
        """Run ingest.ingest() in a background thread and show progress."""
        self.reindex_btn.configure(state="disabled")
        self.progress_bar.pack(padx=16, pady=(2, 0))
        self.progress_bar.start()
        self.status.configure(text="Re-indexing… (this may take a while)")
        threading.Thread(target=self._run_reindex, daemon=True).start()

    def _run_reindex(self):
        try:
            rows, _stats = ingest.ingest(use_ai=True, log=self._ingest_log)
            n = len(rows)
            self.q.put(lambda: self._reindex_done(n, None))
        except Exception as exc:  # noqa: BLE001
            self.q.put(lambda e=exc: self._reindex_done(0, e))

    def _reindex_done(self, n, exc):
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.reindex_btn.configure(state="normal")
        if exc is not None:
            self.status.configure(text=f"Re-index failed: {exc}")
        else:
            self.reload()
            self.status.configure(text=f"Re-index complete: {n} file(s) indexed.")

    def _refresh_types(self):
        types = sorted({r.get("doc_type") for r in self.catalog if r.get("doc_type")})
        self.type_menu.configure(values=[self.ALL_TYPES] + types)
        types = sorted({r.get("doc_type") for r in self.catalog if r.get("doc_type")})
        self.type_menu.configure(values=[self.ALL_TYPES] + types)
        if self.type_var.get() not in [self.ALL_TYPES] + types:
            self.type_var.set(self.ALL_TYPES)

    def reload(self):
        self.catalog = searchlib.load_catalog()
        self._refresh_types()
        self.start()

    def close(self):
        if self._after:
            self.root.after_cancel(self._after)
        self.root.destroy()

    def poll(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        self._after = self.root.after(100, self.poll)

    def put(self, name, text):
        w = self.texts[name]
        w.configure(state="normal")
        w.delete("1.0", "end")
        w.insert("end", text)
        w.configure(state="disabled")

    def _limit(self):
        v = self.n.get()
        return None if v == "All" else int(v)

    # --- search
    def start(self):
        if not self.catalog:
            self.status.configure(text=f"No catalog. Run: python ingest.py (reads {INFORMATION_DIR.name}/).")
            return
        kw = self.entry.get().strip()
        doc_type = None if self.type_var.get() == self.ALL_TYPES else self.type_var.get()
        # read date range filter values
        from_y = self.from_year_entry.get().strip()
        to_y = self.to_year_entry.get().strip()
        try:
            self._from_year = int(from_y) if from_y else None
        except ValueError:
            self._from_year = None
        try:
            self._to_year = int(to_y) if to_y else None
        except ValueError:
            self._to_year = None
        self._seq += 1
        threading.Thread(
            target=self.run,
            args=(self._seq, kw, self._limit(), doc_type, self._from_year, self._to_year),
            daemon=True,
        ).start()

    def run(self, seq, kw, limit, doc_type, from_year=None, to_year=None):
        try:
            results = searchlib.search_documents(self.catalog, kw, limit, doc_type)
            results = self._apply_date_filter(results, from_year, to_year)
            results = self._apply_sort(results)
        except Exception as exc:  # noqa: BLE001 - keep the GUI alive, show the reason
            self.q.put(lambda: self.status.configure(text=f"Search failed: {exc}"))
            return
        self.q.put(lambda: seq == self._seq and self.render(kw, results))

    # --- Q&A
    def ask(self):
        if not self.catalog:
            self._set_answer(f"No catalog. Run: python ingest.py (reads {INFORMATION_DIR.name}/).", [])
            return
        question = self.ask_entry.get().strip()
        if not question:
            return
        self.tabs.set("Ask")
        self._set_answer("Thinking…", [])
        threading.Thread(target=self._run_ask, args=(question,), daemon=True).start()

    def _run_ask(self, question):
        try:
            answer, sources = answer_question(self.catalog, question)
        except Exception as exc:  # noqa: BLE001
            answer, sources = f"Something went wrong: {exc}", []
        self.q.put(lambda: self._set_answer(answer, sources))

    def _set_answer(self, text, sources):
        self.answer_box.configure(state="normal")
        self.answer_box.delete("1.0", "end")
        self.answer_box.insert("end", text)
        self.answer_box.configure(state="disabled")
        clear(self.ask_sources)
        if not sources:
            label(self.ask_sources, "No sources.", 12, MUTED).pack(anchor="w", padx=6, pady=6)
            return
        for i, r in enumerate(sources, 1):
            self._doc_card(self.ask_sources, r, prefix=f"[{i}] ")

    # --- rendering
    def render(self, kw, results):
        self._last_results = list(results)
        total = len(self.catalog)
        header = "all documents" if not kw else f'"{kw}"'
        note = "  ·  showing documents that contain ANY of your words" if results and results[0].get("_match") == "any" else ""
        # date filter note
        date_note = ""
        if self._from_year is not None or self._to_year is not None:
            from_s = str(self._from_year) if self._from_year is not None else "…"
            to_s = str(self._to_year) if self._to_year is not None else "…"
            date_note = f"  ·  filtered to {from_s}–{to_s}"
        self.status.configure(text=f"{len(results)} result(s) for {header} · {total} documents in catalog{note}{date_note}")
        for f in self.frames.values():
            clear(f)
        self.render_documents(results)
        self.render_by_type(results)
        self.render_keywords(results)
        self.put("SIMPLE", build_simple(kw, results, total))
        self.put("ADVANCED", build_advanced(kw, results, total))
        self.tabs.set("Documents")

    def _doc_card(self, parent, r, prefix=""):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", anchor="w", padx=8, pady=6)
        meta = " · ".join(x for x in (r.get("doc_type", ""), human_size(r.get("size_bytes")), r.get("_date_s", "")) if x)
        label(f, meta, 11, PATH_GREEN).pack(anchor="w")
        head = ctk.CTkFrame(f, fg_color="transparent")
        head.pack(anchor="w", fill="x")
        clickable(head, prefix + r.get("file_name", "(unnamed)"), lambda row=r: self._open(row)).pack(side="left")
        clickable(head, "show in folder", lambda row=r: self._reveal(row), size=11, color=MUTED).pack(side="left", padx=12)
        if r.get("_snippet"):
            label(f, "…" + r["_snippet"] + "…", 13).pack(anchor="w")
        elif r.get("summary"):
            label(f, trunc(r["summary"], 300), 13).pack(anchor="w")
        if r.get("_kw_list"):
            label(f, "keywords: " + ", ".join(r["_kw_list"][:8]), 11, MUTED).pack(anchor="w")
        if r.get("status") and r["status"] not in ("ok", "no text"):
            label(f, f"status: {r['status']}", 11, MUTED).pack(anchor="w")

    def _open(self, row):
        if not open_file(row):
            self.status.configure(text=f"Could not open: {resolve_path(row)}")

    def _reveal(self, row):
        if not reveal_file(row):
            self.status.configure(text=f"Could not find: {resolve_path(row)}")

    def render_documents(self, results):
        p = self.frames["Documents"]
        if not results:
            label(p, "No matching documents.", 14).pack(pady=20)
            return
        for r in results:
            self._doc_card(p, r)

    def render_by_type(self, results):
        p = self.frames["By Type"]
        if not results:
            label(p, "No matching documents.", 14).pack(pady=20)
            return
        groups = collections.defaultdict(list)
        for r in results:
            groups[r.get("doc_type", "Other")].append(r)
        for t, xs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            label(p, f"{t}  ({len(xs)})", 16, bold=True).pack(anchor="w", padx=8, pady=(14, 2))
            for r in xs:
                self._doc_card(p, r)

    def render_keywords(self, results):
        p = self.frames["Keywords"]
        counter = collections.Counter(k.lower() for r in results for k in r.get("_kw_list", []))
        if not counter:
            label(p, "No keywords recorded. Run: python ingest.py --rebuild", 14).pack(pady=20)
            return
        label(p, "Click a keyword to search for it.", 12, MUTED).pack(anchor="w", padx=8, pady=(6, 8))
        for kw, c in counter.most_common(60):
            row = ctk.CTkFrame(p, fg_color="transparent")
            row.pack(fill="x", anchor="w", padx=8, pady=2)
            clickable(row, f"{kw}  ({c})", lambda k=kw: self._search_for(k), size=14).pack(side="left")

    def _search_for(self, kw):
        self.entry.delete(0, "end")
        self.entry.insert(0, f'"{kw}"' if " " in kw else kw)
        self.start()


if __name__ == "__main__":
    ctk.set_default_color_theme("blue")      # "blue", "green" or "dark-blue"
    root = ctk.CTk()
    App(root)
    root.mainloop()
