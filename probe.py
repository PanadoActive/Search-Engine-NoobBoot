"""Environment probe for the document-ingestion pipeline.

Reports which optional libraries and external tools are available so you can
tell at a glance what ingest.py / index.py can do in this environment. Nothing
here is required to run the probe itself - it only inspects, never installs.

Run:
    python probe.py
Output is printed and also written to probe.txt (next to this script).
"""

import importlib.util
import os
import shutil
import sqlite3
import sys

from config import BASE_DIR, DB_FILE

# (import name, pip package, what it enables)
LIBRARIES = [
    ("pdfplumber", "pdfplumber", "PDF text extraction"),
    ("openpyxl", "openpyxl", "Excel (.xlsx) extraction"),
    ("xlrd", "xlrd", "old Excel (.xls) extraction (optional)"),
    ("docx", "python-docx", "Word (.docx) extraction"),
    ("PIL", "Pillow", "image handling"),
    ("easyocr", "easyocr", "image OCR (current engine)"),
    ("torch", "torch", "EasyOCR backend"),
    ("pytesseract", "pytesseract", "legacy OCR wrapper (optional)"),
    ("groq", "groq", "AI keywords via Groq"),
    ("google.genai", "google-genai", "AI keywords via Gemini"),
    ("dotenv", "python-dotenv", "loading a .env file"),
    ("googleapiclient", "google-api-python-client", "Google Drive sync"),
    ("google.oauth2", "google-auth", "Google auth"),
    ("google_auth_oauthlib", "google-auth-oauthlib", "Google Drive OAuth flow"),
    ("customtkinter", "customtkinter", "search GUI (index.py)"),
]

# External (non-pip) tools worth knowing about.
EXECUTABLES = [
    ("tesseract", "Tesseract OCR engine (only needed for the legacy pytesseract path)"),
]

# Environment variables the pipeline looks for.
ENV_VARS = ["GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"]

# Credential files Google Drive sync looks for (see ingest.py).
CRED_FILES = ["service_account.json", "credentials.json", "token.json"]  # looked up next to this script


def has_module(name):
    """True if an import spec exists for `name` (supports dotted names)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def has_fts5():
    """True if this Python's SQLite supports FTS5 (needed for full-text search)."""
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.Error:
        return False


def main():
    try:  # ingest.py reads a .env file too, so report keys from it as well
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
    except ImportError:
        pass
    lines = []
    lines.append(f"Python: {sys.version.splitlines()[0]}")
    lines.append(f"Executable: {sys.executable}")
    lines.append(f"Project dir: {BASE_DIR}")
    lines.append("")

    lines.append("Libraries")
    lines.append("-" * 60)
    missing = []
    for import_name, pip_name, purpose in LIBRARIES:
        ok = has_module(import_name)
        mark = "OK " if ok else "-- "
        lines.append(f"  [{mark}] {import_name:<22} {purpose}")
        if not ok:
            missing.append(pip_name)

    lines.append("")
    lines.append("Search index")
    lines.append("-" * 60)
    lines.append(f"  [{'OK ' if has_fts5() else '-- '}] SQLite FTS5 support (required for full-text search)")
    lines.append(f"  [{'OK ' if DB_FILE.exists() else '-- '}] {DB_FILE.name} built (run: python ingest.py)")

    lines.append("")
    lines.append("External tools")
    lines.append("-" * 60)
    for exe, purpose in EXECUTABLES:
        present = shutil.which(exe) is not None
        mark = "OK " if present else "-- "
        lines.append(f"  [{mark}] {exe:<22} {purpose}")

    lines.append("")
    lines.append("API keys (environment)")
    lines.append("-" * 60)
    any_key = False
    for var in ENV_VARS:
        present = bool(os.environ.get(var))
        any_key = any_key or present
        mark = "set" if present else "unset"
        lines.append(f"  {var:<16} {mark}")
    lines.append(
        f"  -> keyword extraction will use: {'AI (LLM)' if any_key else 'local fallback'}"
    )

    lines.append("")
    lines.append("Google Drive credential files")
    lines.append("-" * 60)
    for name in CRED_FILES:
        present = (BASE_DIR / name).exists()
        mark = "found" if present else "missing"
        lines.append(f"  {name:<24} {mark}")

    if missing:
        lines.append("")
        lines.append("To enable everything that's missing:")
        lines.append("  pip install " + " ".join(sorted(set(missing))))

    report = "\n".join(lines)
    print(report)
    with open(BASE_DIR / "probe.txt", "w", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    main()
