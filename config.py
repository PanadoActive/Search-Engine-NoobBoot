"""Shared paths and settings for every script in the project.

All paths are anchored to this file's folder, so the tools work no matter
which directory you launch them from (double-click, IDE, terminal...).
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INFORMATION_DIR = BASE_DIR / "information"
CSV_FILE = BASE_DIR / "data.csv"          # human-readable catalog (open it in Excel)
DB_FILE = BASE_DIR / "search_index.db"    # full-text index (generated, safe to delete)

MAX_SUMMARY = 240          # chars for the one-sentence summary
MAX_KEYWORDS = 8           # keywords stored per file
LLM_INPUT_CHARS = 6000     # how much text to send to the LLM per file
MAX_TEXT_CHARS = 500_000   # text kept per file in the search index
MAX_PDF_PAGES = 300        # stop reading very long PDFs after this many pages
MAX_TEXT_FILE_BYTES = 20 * 1024 * 1024

CHUNK_WORDS = 150          # passage size for the search index
CHUNK_OVERLAP = 30

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}
EXCEL_EXTS = {".xlsx", ".xlsm", ".xls"}
TEXT_EXTS = {".txt", ".md", ".csv"}

FIELDNAMES = ["doc_id", "file_name", "relative_path", "doc_type", "size_bytes",
              "modified", "status", "summary", "keywords"]
