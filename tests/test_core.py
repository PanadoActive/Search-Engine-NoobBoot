"""Run with:  python -m unittest discover -s tests -v   (from the project folder)"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ingest      # noqa: E402
import searchlib   # noqa: E402
import extract_data  # noqa: E402
import llm  # noqa: E402


def write(root, name, text):
    p = Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class QueryParsing(unittest.TestCase):
    def test_words_phrases_and_type(self):
        self.assertEqual(searchlib.parse_query('budget "committee minutes" type:pdf'),
                         (["budget"], ["committee minutes"], "PDF"))

    def test_stop_words_dropped_but_kept_if_alone(self):
        self.assertEqual(searchlib.parse_query("what is the budget")[0], ["budget"])
        self.assertEqual(searchlib.parse_query("of the")[0], ["of", "the"])   # old code returned EVERYTHING here

    def test_short_terms_survive(self):
        self.assertEqual(searchlib.parse_query("q1")[0], ["q1"])

    def test_fts_syntax_cannot_break_the_query(self):
        words, phrases, _ = searchlib.parse_query('foo" OR NEAR( * ) AND ^')
        self.assertTrue(all(w.isalnum() or "_" in w for w in words))

    def test_chunking(self):
        self.assertEqual(searchlib.chunk_text(""), [])
        self.assertEqual(len(searchlib.chunk_text("w " * 150)), 1)            # no duplicate trailing window
        sizes = [len(c.split()) for c in searchlib.chunk_text("w " * 400)]
        self.assertEqual(sizes, [150, 150, 150, 40])

    def test_chunk_text_empty(self):
        self.assertEqual(searchlib.chunk_text(""), [])
        self.assertEqual(searchlib.chunk_text("   "), [])


class TextBuilders(unittest.TestCase):
    def _import_index(self):
        # index.py imports customtkinter which may not be installed in CI.
        # We test the pure-Python helpers directly from index.py source.
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location(
            "index_mod",
            str(Path(__file__).resolve().parent.parent / "index.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            self.skipTest("customtkinter not installed or index.py failed to load")
        return mod

    def test_build_simple_no_catalog(self):
        from index import build_simple
        out = build_simple("budget", [], 0)
        self.assertIn("No catalog", out)

    def test_build_simple_no_results(self):
        from index import build_simple
        out = build_simple("budget", [], 5)
        self.assertIn("No documents matched", out)

    def test_build_advanced_with_result(self):
        from index import build_advanced
        row = {
            "file_name": "a.pdf",
            "doc_type": "PDF",
            "_snippet": "foo",
            "summary": "bar",
            "_kw_list": ["x"],
            "_dt": None,
            "_date_s": "",
            "size_bytes": 1000,
            "relative_path": "a.pdf",
        }
        out = build_advanced("test", [row], 1)
        self.assertIn("PDF", out)


class ExtractDataTests(unittest.TestCase):
    def test_extract_data_missing_path(self):
        with tempfile.TemporaryDirectory() as d:
            missing = os.path.join(d, "nofile.csv")
            with self.assertRaises(FileNotFoundError):
                extract_data.extract_data(missing)


class LlmTests(unittest.TestCase):
    def test_llm_no_client(self):
        # Ensure no stale cached client from a previous test run in the same process
        import llm as llm_mod
        llm_mod._client = None
        # Temporarily clear env keys so get_client() returns None
        import os
        saved = {}
        for key in ("GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
            saved[key] = os.environ.pop(key, None)
        try:
            result = llm_mod.complete("hello", max_tokens=10)
            self.assertIsNone(result)
        finally:
            for key, val in saved.items():
                if val is not None:
                    os.environ[key] = val
            llm_mod._client = None  # reset so other tests aren't affected


class IngestAndSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.info = self.t / "information"
        self.csv = self.t / "data.csv"
        self.db = self.t / "index.db"
        write(self.info, "budget_minutes.txt",
              "The committee approved the annual budget. " + "filler " * 300 + "The zebra crossing project was postponed.")
        write(self.info, "recipes.md", "Pancakes need flour, eggs and milk. Whisk the batter until smooth.")
        write(self.info, "sub/notes.txt", "Quarterly infrastructure report: servers upgraded in Q1.")
        write(self.info, "README.txt", "this file is skipped")

    def tearDown(self):
        self.tmp.cleanup()

    def run_ingest(self, **kw):
        return ingest.ingest(self.info, self.csv, self.db, use_ai=False, log=lambda *_: None, **kw)

    def search(self, q, **kw):
        catalog = searchlib.load_catalog(self.csv)
        return searchlib.search_documents(catalog, q, db_path=self.db, **kw)

    def test_readme_skipped_and_rows_written(self):
        rows, _ = self.run_ingest()
        self.assertEqual(sorted(r["file_name"] for r in rows), ["budget_minutes.txt", "notes.txt", "recipes.md"])

    def test_finds_words_deep_in_the_body(self):
        self.run_ingest()
        hits = self.search("zebra")                  # not in summary or keywords - only deep in the text
        self.assertEqual([h["file_name"] for h in hits], ["budget_minutes.txt"])
        self.assertIn("«zebra»", hits[0]["_snippet"])

    def test_stemming_phrase_type_and_fallback(self):
        self.run_ingest()
        self.assertEqual(self.search("pancake")[0]["file_name"], "recipes.md")           # porter stemming
        self.assertEqual(self.search('"annual budget"')[0]["file_name"], "budget_minutes.txt")
        self.assertEqual({h["doc_type"] for h in self.search("budget flour")}, {"Text"})
        any_hits = self.search("flour zebra")        # no single doc has both -> OR fallback
        self.assertEqual(len(any_hits), 2)
        self.assertEqual(any_hits[0]["_match"], "any")
        self.assertEqual(self.search("zebra", doc_type="PDF"), [])
        self.assertEqual(self.search("zebra type:text")[0]["file_name"], "budget_minutes.txt")

    def test_filename_and_empty_queries(self):
        self.run_ingest()
        self.assertEqual(self.search("recipes")[0]["file_name"], "recipes.md")           # title match
        self.assertEqual(len(self.search("")), 3)                                        # browse mode
        self.assertEqual(self.search("nonexistentword"), [])

    def test_passages_for_qa(self):
        self.run_ingest()
        ps = searchlib.passages("what happened to the zebra crossing project", k=3, path=self.db)
        self.assertTrue(ps and "zebra" in ps[0]["text"])
        self.assertEqual(ps[0]["rel_path"], "budget_minutes.txt")

    def test_incremental_cache_and_change_detection(self):
        self.run_ingest()
        _, stats = self.run_ingest()
        self.assertEqual(stats["reused"], 3)
        time.sleep(0.05)
        p = write(self.info, "recipes.md", "Now it is about waffles and syrup.")
        os.utime(p, (time.time() + 5, time.time() + 5))
        _, stats = self.run_ingest()
        self.assertEqual(stats["reused"], 2)
        self.assertEqual(self.search("waffles")[0]["file_name"], "recipes.md")
        self.assertEqual(self.search("pancakes"), [])                                    # old text gone from index

    def test_deleted_files_leave_catalog_and_index(self):
        self.run_ingest()
        (self.info / "recipes.md").unlink()
        _, stats = self.run_ingest()
        self.assertEqual(stats["removed from index"], 1)
        self.assertEqual(self.search("pancakes"), [])

    def test_missing_index_falls_back_to_catalog(self):
        self.run_ingest()
        os.remove(self.db)
        hits = self.search("recipes")
        self.assertEqual(hits[0]["file_name"], "recipes.md")

    def test_index_is_rebuilt_when_missing_but_csv_cached(self):
        self.run_ingest()
        os.remove(self.db)
        _, stats = self.run_ingest()                      # CSV says "unchanged" but the index is gone
        self.assertEqual(stats.get("reused", 0), 0)
        self.assertEqual(self.search("zebra")[0]["file_name"], "budget_minutes.txt")


class Extractors(unittest.TestCase):
    def test_docx_and_xlsx_roundtrip(self):
        try:
            import docx
            import openpyxl
        except ImportError:
            self.skipTest("python-docx/openpyxl not installed")
        with tempfile.TemporaryDirectory() as d:
            dp, xp = os.path.join(d, "a.docx"), os.path.join(d, "b.xlsx")
            doc = docx.Document()
            doc.add_paragraph("Onboarding checklist for new hires")
            doc.save(dp)
            wb = openpyxl.Workbook()
            wb.active.append(["Server", "Status"])
            wb.active.append(["alpha", "online"])
            wb.save(xp)
            self.assertIn("Onboarding", ingest.extract(dp, ".docx")[0])
            text, status = ingest.extract(xp, ".xlsx")
            self.assertEqual(status, "ok")
            self.assertIn("alpha | online", text)

    def test_unsupported_and_keywords(self):
        self.assertTrue(ingest.extract("x.bin", ".bin")[1].startswith("skipped"))
        kws, method = ingest.extract_keywords("Solar panels convert sunlight. Solar panels need sunlight.", use_ai=False)
        self.assertEqual(method, "local")
        self.assertIn("solar panels", kws)
        self.assertEqual(ingest.extract_keywords("   ", use_ai=False), ("", "none"))


if __name__ == "__main__":
    unittest.main()
