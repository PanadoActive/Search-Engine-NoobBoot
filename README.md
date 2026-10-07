Group 03: Vortex
Member #1: Wong Ik Chan
Member #2: Fernando Li Zhe CHONG

This program tries to help with the problem of overflow in information by creating a library of imported data into a "search engine" lookalike. This local search engine has a lot of positives compared to conventional store in folder as it not just records the name of the files but also finds keywords and themes within the text using ai as well as an "ask me" section to find relevent files using questions powered by Grok.

## Setup

Place your files in the `information/` folder (subfolders are fine), then run:

```bash
pip install -r requirements.txt     # install dependencies
python ingest.py                    # scan information/ → data.csv + search_index.db
python index.py                     # open the search window
```

Re-run `ingest.py` whenever files change — unchanged files are skipped automatically.
You can also click the **Re-index** button inside the GUI to re-index without opening a terminal.

![alt text](image.png)
![alt text](image-1.png)
![alt text](image-2.png)

## Features

| Feature | Description |
|---|---|
| **Full-text search** | BM25-ranked search across every word in every document (PDF, Word, Excel, text, images) |
| **Phrase search** | Use `"exact phrase"` to match words next to each other |
| **Type filter** | Add `type:pdf`, `type:excel`, `type:word`, `type:image`, or `type:text` to your query, or use the dropdown |
| **Date range filter** | Filter results by year using the From / To fields in the top bar |
| **Sort options** | Sort results by Relevance, Newest, Oldest, or Name A→Z / Z→A |
| **Folder sidebar** | Browse and filter by subfolder/department from the left panel |
| **Ask tab** | Ask a plain-English question; the engine finds matching passages and optionally generates a cited answer via Groq or Gemini |
| **By Type tab** | Same results grouped by document type |
| **Keywords tab** | Most common keywords across matching documents; click any to search for it |
| **SIMPLE / ADVANCED tabs** | Plain-text summaries of the current results |
| **Search history** | Last 20 queries saved; click the search box to see and re-run previous searches |
| **Built-in text viewer** | Click any `.txt` or `.md` result to read it inline with search terms highlighted |
| **Export CSV** | Save the current result list to a CSV file with the Export CSV button |
| **Re-index button** | Re-run ingestion from inside the GUI with a live progress bar — no terminal needed |
| **Dark / light mode** | Toggle with the button in the top bar; preference is remembered across sessions |

## Search tips

| You type | Meaning |
|---|---|
| `budget report` | documents with all the words (falls back to *any* word if none has them all) |
| `"exact phrase"` | words next to each other |
| `budget type:pdf` | only PDF documents |
| *(empty)* | list everything, newest first |

Searching is stemmed (`budgets` finds `budget`) and ranked with BM25. Matches in a file's name or keywords count 6× more than body text.

## Dependencies

### Standard library (built-in, no install needed)

| Module | Purpose |
|---|---|
| `sqlite3` | FTS5 full-text index and BM25 search |
| `csv` | Read/write `data.csv` catalog |
| `re` | Query parsing and text cleaning |
| `pathlib` | Path manipulation |
| `os` | File system and environment variables |
| `sys` | Platform detection and CLI arguments |
| `threading` | Background search and ingest threads |
| `queue` | Thread-safe GUI updates |
| `collections` | Counter, defaultdict, OrderedDict |
| `datetime` | Date parsing and mtime stamps |
| `tempfile` | Atomic file writes |
| `shutil` | Detect external executables |
| `importlib.util` | Module availability checks |
| `subprocess` | Open files and reveal in file manager |
| `webbrowser` | Fallback file opener |
| `argparse` | CLI flags (`--rebuild`, `--no-ai`) |
| `contextlib` | `closing()` and `suppress()` helpers |
| `tkinter.filedialog` | Export CSV save dialog |
| `json` | Read/write `.prefs.json` |

### Third-party (install via pip)

| Package | Version | Required? | Purpose |
|---|---|---|---|
| `customtkinter` | `>=5.2,<6` | **Required** | Desktop GUI (themed Tkinter) |
| `pdfplumber` | `>=0.10,<1` | Optional | PDF text extraction |
| `openpyxl` | `>=3.1,<4` | Optional | `.xlsx` / `.xlsm` extraction |
| `python-docx` | `>=1.0,<2` | Optional | `.docx` (Word) extraction |
| `xlrd` | `>=2.0,<3` | Optional | `.xls` (old Excel) extraction |
| `python-dotenv` | `>=1.0,<2` | Optional | Load API keys from a `.env` file |
| `groq` | `>=0.9` | Optional | AI keywords and Q&A via Groq LLM |
| `google-genai` | `>=1.0,<2` | Optional | AI keywords and Q&A via Gemini LLM |
| `easyocr` | `>=1.7,<2` | Optional | OCR for image files (pulls in PyTorch — large download) |

**Minimum install** (GUI + search only, no PDF/Excel/OCR):
```bash
pip install customtkinter
```

**Full install:**
```bash
pip install -r requirements.txt
```

Run `python probe.py` to check which dependencies and API keys are available in your environment.

### External tools (not pip)

| Tool | Required? | Purpose |
|---|---|---|
| `tesseract` | Optional | Legacy OCR engine (only needed if using the `pytesseract` path instead of the default EasyOCR) |

## Files

| File | Purpose |
|---|---|
| `ingest.py` | Reads files → `data.csv` (summary, keywords) and `search_index.db` (full text) |
| `searchlib.py` | SQLite FTS5 index, query parsing, BM25 ranking |
| `index.py` | CustomTkinter search window |
| `extract_data.py` | The same search from the command line: `python extract_data.py "exact phrase" type:pdf` |
| `llm.py` | Optional Groq / Gemini helper (keywords and Ask answers) |
| `config.py` | Paths and limits (everything is relative to the project folder) |
| `probe.py` | Checks which libraries, keys, and features are available |
| `tests/` | `python -m unittest discover -s tests -v` |

## Generated files (safe to delete)

| File | Contents |
|---|---|
| `data.csv` | Human-readable catalog — one row per document |
| `search_index.db` | SQLite FTS5 full-text index |
| `.prefs.json` | UI preferences (dark mode, search history, folder filter) |
| `probe.txt` | Last output of `probe.py` |

## Common commands

```bash
# Ingest documents
python ingest.py              # incremental; AI keywords if a key is set
python ingest.py --rebuild    # reprocess everything, ignore cache
python ingest.py --no-ai      # local extraction only, nothing sent externally

# Run the GUI
python index.py

# CLI search
python extract_data.py                          # list all documents
python extract_data.py budget report            # full-text search
python extract_data.py "exact phrase" type:pdf  # phrase + type filter

# Environment probe
python probe.py

# Run tests
python -m unittest discover -s tests -v
```

## Optional AI

Put `GROQ_API_KEY=...` or `GOOGLE_API_KEY=...` in a `.env` file next to the scripts. Model names can be overridden with `GROQ_MODEL` / `GEMINI_MODEL` in `.env`.

**Privacy:** with a key set, the first ~6,000 characters of each document (at ingest time) and the matching passages (when you use the Ask tab) are sent to that provider. Run `python ingest.py --no-ai` to keep everything local — nothing leaves your machine.

## Privacy and git

`information/`, `data.csv`, and `search_index.db` contain your documents' text, so `.gitignore` excludes them. If they were already committed, remove them from tracking:

```bash
git rm -r --cached information data.csv search_index.db
```

Note that they remain in the repo's history — make the repo private or rewrite history if it was public.
