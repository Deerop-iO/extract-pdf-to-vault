"""End-to-end smoke test: extract -> build -> verify on a generated fixture PDF.

Unlike test_lib (pure helpers, needs only PyYAML), this exercises the real
pipeline against a tiny PDF built on the fly with PyMuPDF. It is skipped when
PyMuPDF / pymupdf4llm are not installed, so the lightweight unit suite still
runs everywhere.

Run from the kit root with the full extraction venv:

    python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest

_KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_KIT_ROOT, "templates", "scripts"))

try:
    import fitz  # PyMuPDF  # noqa: F401
    import pymupdf4llm  # noqa: F401
    import extract as extract_mod
    import build_vault
    import verify_vault

    _HAVE_PDF_STACK = True
except Exception:  # pragma: no cover - exercised only when deps are absent
    _HAVE_PDF_STACK = False


def _make_fixture_pdf(path: str) -> None:
    """A 3-page PDF with embedded bookmarks and a wargame-style stat line.

    The stat line ('M WS BS S T W I A ...') is the false-positive the spaced-
    caps fix must NOT touch -- the smoke test asserts it survives verbatim.
    """
    doc = fitz.open()
    bodies = [
        # Page 1
        "Introduction\n\n"
        "This is a deterministic fixture document used by the smoke test. "
        "It contains enough prose to clear the scanned-PDF text threshold so "
        "extraction proceeds normally instead of bailing out as image-only. "
        "We repeat a few sentences to be safe. The quick brown fox jumps over "
        "the lazy dog. The quick brown fox jumps over the lazy dog again.",
        # Page 2
        "Playing the Game\n\n"
        "Combat is resolved by comparing fighter profiles. More filler prose "
        "so the page carries real extractable text for pymupdf4llm to parse "
        "into markdown. Another sentence to pad the body out comfortably.",
        # Page 3
        "Bestiary\n\n"
        "A representative fighter profile is shown below.\n\n"
        "M WS BS S T W I A Ld Cl Wil Int\n"
        '5" 4+ 4+ 3 3 1 4+ 1 7+ 7+ 8+ 7+\n\n'
        "These single-letter columns are data, not a spaced-out word.",
    ]
    for text in bodies:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
    # Embedded ToC: [level, title, 1-based start page].
    doc.set_toc(
        [
            [1, "Introduction", 1],
            [1, "Playing the Game", 2],
            [1, "Bestiary", 3],
        ]
    )
    doc.set_metadata({"title": "Smoke Test Rulebook", "author": "p2v tests"})
    doc.save(path)
    doc.close()


@unittest.skipUnless(_HAVE_PDF_STACK, "PyMuPDF / pymupdf4llm not installed")
class TestPipelineSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pdf = os.path.join(self.tmp, "fixture.pdf")
        self.out = os.path.join(self.tmp, ".p2v")
        self.vault = os.path.join(self.tmp, "vault")
        os.makedirs(self.out, exist_ok=True)
        os.makedirs(self.vault, exist_ok=True)
        _make_fixture_pdf(self.pdf)

    def test_extract_build_verify(self):
        cfg = extract_mod._load_config(None)
        manifest = extract_mod.extract(self.pdf, self.out, cfg, None)

        # Extraction produced a ToC-faithful manifest.
        self.assertEqual(manifest["toc_source"], "embedded")
        self.assertEqual(len(manifest["sections"]), 3)
        leaves = [s for s in manifest["sections"] if s["is_leaf"]]
        self.assertEqual(len(leaves), 3)

        owned = build_vault.build(
            manifest, self.vault, set(), layout="nested", index_link_mode="root"
        )
        self.assertTrue(owned)
        self.assertTrue(os.path.exists(os.path.join(self.vault, "index.md")))

        failures = verify_vault.verify(self.vault, verify_vault.DEFAULT_GATES, [])
        self.assertEqual(failures, [], f"verify gates failed: {failures}")

    def test_stat_line_preserved_through_pipeline(self):
        cfg = extract_mod._load_config(None)
        manifest = extract_mod.extract(self.pdf, self.out, cfg, None)
        build_vault.build(
            manifest, self.vault, set(), layout="nested", index_link_mode="root"
        )
        # The Bestiary leaf note must still contain the un-collapsed stat header.
        joined = ""
        for root, _dirs, files in os.walk(self.vault):
            for f in files:
                if f.endswith(".md"):
                    with open(os.path.join(root, f), encoding="utf-8") as fh:
                        joined += fh.read()
        self.assertIn("S T W I A", joined)
        self.assertNotIn("STWIA", joined)


def _make_branch_preamble_pdf(path: str) -> None:
    """A 4-page PDF whose chapter 2 ("Gang List", p2) carries body content on
    pages 2-3 but only bookmarks one subsection ("Exotic Beasts", p4). Pages 2-3
    are the branch *preamble* the old leaf/branch split dropped. Each preamble
    page carries a unique marker the smoke test asserts survives into the branch
    folder note.
    """
    doc = fitz.open()
    # Short lines (insert_text does not wrap; long lines clip at the page edge
    # and would fall under the scanned-PDF text threshold). Each page carries
    # several lines so total extracted text comfortably clears min_text_chars.
    bodies = [
        # Page 1 - Introduction (leaf)
        [
            "Introduction",
            "Deterministic fixture document.",
            "It carries enough prose to clear",
            "the scanned-PDF text threshold.",
            "The quick brown fox jumps over",
            "the lazy dog, again and again.",
        ],
        # Page 2 - Gang List chapter opener (branch preamble, page 1 of 2)
        [
            "Gang List",
            "PREAMBLE_MARKER_ALPHA opener text.",
            "These unit entries live above the",
            "single bookmarked subsection, so",
            "they must land in the branch note.",
            "Filler prose for extractable text.",
        ],
        # Page 3 - more gang-list content (branch preamble, page 2 of 2)
        [
            "PREAMBLE_MARKER_BETA continues here",
            "on the second preamble page with",
            "additional unit entries and rules.",
            "More filler prose so the page",
            "parses into markdown comfortably.",
        ],
        # Page 4 - Exotic Beasts (the one bookmarked child leaf)
        [
            "Exotic Beasts",
            "CHILD_MARKER subsection content.",
            "Filler prose to give the leaf real",
            "extractable text for the extractor",
            "to slice into its own leaf note.",
        ],
    ]
    for lines in bodies:
        page = doc.new_page()
        page.insert_text((72, 72), "\n".join(lines), fontsize=11)
    doc.set_toc(
        [
            [1, "Introduction", 1],
            [1, "Gang List", 2],
            [2, "Exotic Beasts", 4],
        ]
    )
    doc.set_metadata({"title": "Preamble Test Rulebook", "author": "p2v tests"})
    doc.save(path)
    doc.close()


@unittest.skipUnless(_HAVE_PDF_STACK, "PyMuPDF / pymupdf4llm not installed")
class TestBranchPreambleSmoke(unittest.TestCase):
    """End-to-end: a branch's preamble pages are captured at extract time and
    rendered into the branch folder note above its Contents list, the vault
    verifies clean, and a second extract+build is byte-identical (idempotent)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pdf = os.path.join(self.tmp, "preamble.pdf")
        self.out = os.path.join(self.tmp, ".p2v")
        self.vault = os.path.join(self.tmp, "vault")
        os.makedirs(self.out, exist_ok=True)
        os.makedirs(self.vault, exist_ok=True)
        _make_branch_preamble_pdf(self.pdf)
        self.branch_note = os.path.join(
            self.vault, "preamble-test-rulebook", "02-gang-list", "02-gang-list.md"
        )

    def _build_once(self) -> str:
        cfg = extract_mod._load_config(None)
        manifest = extract_mod.extract(self.pdf, self.out, cfg, None)
        gang = next(s for s in manifest["sections"] if s["title"] == "Gang List")
        self.assertFalse(gang["is_leaf"])  # it has a child -> branch
        self.assertIn("PREAMBLE_MARKER_ALPHA", gang.get("markdown", ""))
        self.assertIn("PREAMBLE_MARKER_BETA", gang.get("markdown", ""))
        build_vault.build(
            manifest, self.vault, set(), layout="nested", index_link_mode="root"
        )
        with open(self.branch_note, encoding="utf-8") as fh:
            return fh.read()

    def test_preamble_captured_rendered_and_verified(self):
        body = self._build_once()
        # Preamble content is in the branch note, above the Contents list.
        self.assertIn("PREAMBLE_MARKER_ALPHA", body)
        self.assertIn("PREAMBLE_MARKER_BETA", body)
        self.assertIn("## Contents", body)
        self.assertLess(
            body.index("PREAMBLE_MARKER_ALPHA"), body.index("## Contents")
        )
        # The child's content stays in the child leaf, not the branch note.
        self.assertNotIn("CHILD_MARKER", body)
        failures = verify_vault.verify(self.vault, verify_vault.DEFAULT_GATES, [])
        self.assertEqual(failures, [], f"verify gates failed: {failures}")

    def test_idempotent_rebuild(self):
        first = self._build_once()
        second = self._build_once()
        self.assertEqual(first, second)


def _make_no_toc_pdf(path: str, page_count: int) -> None:
    """A PDF with NO embedded ToC (never calls set_toc). Its own page text is
    irrelevant to the heading-fallback wiring tests below, which monkeypatch
    to_markdown to supply canned page chunks; only page_count / no-ToC matter."""
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page()
        page.insert_text((72, 72), f"placeholder page {i + 1}", fontsize=11)
    doc.set_metadata({"title": "No ToC Rulebook", "author": "p2v tests"})
    doc.save(path)
    doc.close()


@unittest.skipUnless(_HAVE_PDF_STACK, "PyMuPDF / pymupdf4llm not installed")
class TestHeadingFallbackSmoke(unittest.TestCase):
    """End-to-end wiring for --fallback headings, deterministic and independent of
    pymupdf4llm's layout classifier: to_markdown is monkeypatched to return canned
    page chunks (some with `##` headings), so extract -> build -> verify is
    exercised without depending on font-geometry heading detection.

    Real-classifier realism is covered separately by manual validation against a
    real no-ToC PDF (see the plan's third test layer).
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pdf = os.path.join(self.tmp, "no_toc.pdf")
        self.out = os.path.join(self.tmp, ".p2v")
        self.vault = os.path.join(self.tmp, "vault")
        os.makedirs(self.out, exist_ok=True)
        os.makedirs(self.vault, exist_ok=True)

    def _run_with_chunks(self, chunks, fallback):
        _make_no_toc_pdf(self.pdf, len(chunks))

        def fake_to_markdown(doc, **kwargs):
            return chunks

        from unittest import mock

        cfg = extract_mod._load_config(None)
        with mock.patch.object(
            extract_mod.pymupdf4llm, "to_markdown", fake_to_markdown
        ):
            return extract_mod.extract(self.pdf, self.out, cfg, fallback)

    @staticmethod
    def _chunk(text):
        # Only "text" is read by extract(); pad past min_text_chars per page.
        return {"text": text + "\n\n" + ("filler prose. " * 40)}

    def test_headings_fallback_extract_build_verify(self):
        chunks = [
            self._chunk("## Introduction\n\nintro body"),
            self._chunk("## Playing The Game\n\nrules body"),
            self._chunk("## Bestiary\n\ncreatures body"),
        ]
        manifest = self._run_with_chunks(chunks, "headings")

        self.assertEqual(manifest["toc_source"], "headings")
        self.assertTrue(manifest["toc_present"])
        titles = [s["title"] for s in manifest["sections"]]
        self.assertEqual(titles, ["Introduction", "Playing The Game", "Bestiary"])
        leaves = [s for s in manifest["sections"] if s["is_leaf"]]
        self.assertEqual(len(leaves), 3)
        self.assertTrue(
            any("reconstructed from" in w for w in manifest["warnings"]),
            manifest["warnings"],
        )

        build_vault.build(
            manifest, self.vault, set(), layout="nested", index_link_mode="root"
        )
        # The inferred-structure callout appears in the per-PDF MOC.
        moc = os.path.join(self.vault, "no-toc-rulebook", "no-toc-rulebook.md")
        with open(moc, encoding="utf-8") as fh:
            self.assertIn("inferred from detected headings", fh.read())

        failures = verify_vault.verify(self.vault, verify_vault.DEFAULT_GATES, [])
        self.assertEqual(failures, [], f"verify gates failed: {failures}")

    def test_headings_fallback_leading_gap_entry(self):
        # First heading on page 2 -> a leading "Page 1" entry captures page 1.
        chunks = [
            self._chunk("plain body, no heading here"),
            self._chunk("## Real Start\n\nbody"),
        ]
        manifest = self._run_with_chunks(chunks, "headings")
        titles = [s["title"] for s in manifest["sections"]]
        self.assertEqual(titles, ["Page 1", "Real Start"])

    def test_headings_fallback_hard_stops_without_headings(self):
        # Enough text to clear the scanned guard, but no `##` heading anywhere.
        chunks = [self._chunk("just prose"), self._chunk("more prose")]
        with self.assertRaises(SystemExit) as ctx:
            self._run_with_chunks(chunks, "headings")
        self.assertIn("no usable heading", str(ctx.exception))

    def test_no_fallback_still_hard_stops(self):
        chunks = [self._chunk("## Has Heading\n\nbody")]
        with self.assertRaises(SystemExit) as ctx:
            self._run_with_chunks(chunks, None)
        self.assertIn("No embedded table of contents", str(ctx.exception))


@unittest.skipUnless(_HAVE_PDF_STACK, "PyMuPDF / pymupdf4llm not installed")
class TestSelectPassthrough(unittest.TestCase):
    """The to_markdown pass-through helper forwards supported keys and warns
    (rather than crashing) when a non-default is asked for on a version that
    lacks the parameter."""

    def test_forwards_explicitly_named_keys(self):
        cfg = {"header": False, "footer": True, "table_strategy": "text"}
        supported = {"header", "footer", "table_strategy", "pages"}
        kwargs, warnings = extract_mod._select_passthrough(cfg, supported)
        self.assertEqual(
            kwargs, {"header": False, "footer": True, "table_strategy": "text"}
        )
        self.assertEqual(warnings, [])

    def test_forwards_all_when_signature_takes_var_kwargs(self):
        # Modern pymupdf4llm wraps to_markdown as (*args, **kwargs): no names,
        # but a **kwargs catch-all -> every option must still be forwarded.
        cfg = {"header": True, "footer": True, "table_strategy": "text"}
        kwargs, warnings = extract_mod._select_passthrough(
            cfg, {"args", "kwargs"}, accepts_var_kw=True
        )
        self.assertEqual(kwargs.get("table_strategy"), "text")
        self.assertEqual(kwargs.get("header"), True)
        self.assertEqual(warnings, [])

    def test_real_signature_forwards_table_strategy(self):
        # Against the actually-installed to_markdown signature.
        import inspect

        sig = inspect.signature(pymupdf4llm.to_markdown)
        supported = set(sig.parameters)
        accepts_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        cfg = extract_mod._load_config(None)
        cfg["table_strategy"] = "text"
        kwargs, warnings = extract_mod._select_passthrough(
            cfg, supported, accepts_var_kw
        )
        self.assertEqual(kwargs.get("table_strategy"), "text")
        self.assertEqual(warnings, [])

    def test_warns_on_unsupported_nondefault(self):
        # An old version with an explicit signature lacking table_strategy and
        # no **kwargs: a non-default value warns rather than crashing.
        cfg = {"header": True, "footer": True, "table_strategy": "text"}
        supported = {"header", "footer"}  # no table_strategy, no var-kw
        kwargs, warnings = extract_mod._select_passthrough(cfg, supported)
        self.assertNotIn("table_strategy", kwargs)
        self.assertEqual(len(warnings), 1)
        self.assertIn("table_strategy", warnings[0])

    def test_silent_when_unsupported_but_default(self):
        # Same old version, but table_strategy left at its default -> no warning.
        cfg = {"header": True, "footer": True, "table_strategy": "lines_strict"}
        supported = {"header", "footer"}
        kwargs, warnings = extract_mod._select_passthrough(cfg, supported)
        self.assertNotIn("table_strategy", kwargs)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
