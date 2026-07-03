"""Unit tests for the pure pipeline helpers shipped in templates/scripts/lib.

Run from the kit root with a venv that has PyYAML installed:

    python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest

_KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_KIT_ROOT, "templates", "scripts"))

from lib import frontmatter, links, naming, toc_tree, table_guard, index_guard  # noqa: E402
from lib.slugify import slugify  # noqa: E402
import build_vault  # noqa: E402
import apply_enrichment  # noqa: E402
import apply_repair  # noqa: E402
from lib.text import (  # noqa: E402
    clean_inline,
    clean_block,
    collapse_spaced_caps,
    split_glued_caps_by_gaps,
    apply_heading_space_map,
    normalize_body,
    reformat_stat_profiles,
    reformat_equipment_lists,
    merge_wrapped_table_rows,
    promote_header_below_separator,
    promote_demoted_label_row,
    collapse_table_headers,
    split_am_traits,
    merge_wrapped_name_rows,
    _profile_header,
    _FIGHTER_COLS,
)
from lib.index_layout import reconstruct_index  # noqa: E402
from lib.heading_toc import toc_from_headings  # noqa: E402
from lib.toc_page import (  # noqa: E402
    toc_from_toc_page,
    embedded_toc_looks_degenerate,
    detect_page_offset,
    _parse_rows,
    _x0_bands,
    _strip_leaders,
)
import verify_vault  # noqa: E402


SAMPLE_TOC = [
    [1, "Introduction", 1],
    [2, "Background", 1],
    [2, "Scope", 3],
    [1, "Methods", 4],
    [2, "Data Collection", 4],
    [1, "Conclusion", 7],
]


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_ascii_fold(self):
        self.assertEqual(slugify("Résumé Déjà"), "resume-deja")

    def test_collapse_and_trim(self):
        self.assertEqual(slugify("  --A  B--  "), "a-b")

    def test_empty_fallback(self):
        self.assertEqual(slugify("***"), "section")
        self.assertEqual(slugify(""), "section")

    def test_truncate_no_trailing_dash(self):
        out = slugify("a" * 100, max_len=10)
        self.assertEqual(out, "a" * 10)
        self.assertEqual(slugify("ab " + "c" * 100, max_len=3), "ab")

    def test_deterministic(self):
        self.assertEqual(slugify("Same Title"), slugify("Same Title"))


class TestTocTree(unittest.TestCase):
    def setUp(self):
        self.sections = toc_tree.build_sections(SAMPLE_TOC, page_count=8)

    def test_numbers_are_positional(self):
        nums = [s["toc_number"] for s in self.sections]
        self.assertEqual(
            nums, ["01", "01.01", "01.02", "02", "02.01", "03"]
        )

    def test_leaf_detection(self):
        leaf = {s["toc_number"]: s["is_leaf"] for s in self.sections}
        self.assertFalse(leaf["01"])  # has children
        self.assertTrue(leaf["01.01"])
        self.assertFalse(leaf["02"])
        self.assertTrue(leaf["03"])  # no children -> leaf

    def test_parent_numbers(self):
        parent = {s["toc_number"]: s["parent_number"] for s in self.sections}
        self.assertIsNone(parent["01"])
        self.assertEqual(parent["01.02"], "01")
        self.assertEqual(parent["02.01"], "02")

    def test_page_ranges(self):
        rng = {s["toc_number"]: (s["start_page"], s["end_page"]) for s in self.sections}
        self.assertEqual(rng["01.01"], (1, 2))  # next sibling starts page 3
        self.assertEqual(rng["01.02"], (3, 3))  # next level-1 starts page 4
        self.assertEqual(rng["03"], (7, 8))  # last section runs to end

    def test_display_title_human_number(self):
        d = {s["toc_number"]: s["display_title"] for s in self.sections}
        self.assertEqual(d["01.02"], "1.2 Scope")
        self.assertEqual(d["01"], "1 Introduction")

    def test_level_jump_is_clamped(self):
        # level 1 then level 3 must not invent a phantom level-2 parent.
        secs = toc_tree.build_sections([[1, "A", 1], [3, "B", 2]], page_count=3)
        self.assertEqual([s["toc_number"] for s in secs], ["01", "01.01"])
        self.assertEqual(secs[1]["level"], 2)

    def test_empty_toc(self):
        self.assertEqual(toc_tree.build_sections([], 10), [])

    def test_pad_widens_past_99(self):
        toc = [[1, f"S{i}", 1] for i in range(1, 101)]
        secs = toc_tree.build_sections(toc, page_count=200)
        self.assertEqual(secs[0]["toc_number"], "001")
        self.assertEqual(secs[99]["toc_number"], "100")

    def test_branch_preamble_range_present(self):
        # A chapter (p34) whose only bookmarked child starts at p49 -> the
        # branch owns the preamble pages 34-48 (the Van Saar gang-list case).
        toc = [[1, "Gang List", 34], [2, "Exotic Beasts", 49], [1, "Next", 51]]
        secs = toc_tree.build_sections(toc, page_count=60)
        by = {s["toc_number"]: s for s in secs}
        self.assertEqual(toc_tree.branch_preamble_range(by["01"], secs), (34, 48))

    def test_branch_preamble_none_when_child_shares_start_page(self):
        # SAMPLE_TOC: "Introduction" (p1) has its first child also on p1.
        by = {s["toc_number"]: s for s in self.sections}
        self.assertIsNone(toc_tree.branch_preamble_range(by["01"], self.sections))

    def test_branch_preamble_none_for_leaf(self):
        by = {s["toc_number"]: s for s in self.sections}
        self.assertIsNone(toc_tree.branch_preamble_range(by["01.01"], self.sections))

    def test_branch_preamble_nested_branch_as_first_child(self):
        # A branch whose first child is itself a branch still gets a preamble;
        # that inner branch, whose own child shares its start page, gets none.
        toc = [[1, "A", 10], [2, "A.1", 15], [3, "A.1.1", 15], [1, "B", 20]]
        secs = toc_tree.build_sections(toc, page_count=30)
        by = {s["toc_number"]: s for s in secs}
        self.assertEqual(toc_tree.branch_preamble_range(by["01"], secs), (10, 14))
        self.assertIsNone(toc_tree.branch_preamble_range(by["01.01"], secs))


class TestText(unittest.TestCase):
    def test_clean_inline_strips_nul(self):
        # PyMuPDF UTF-16 bookmark titles arrive with trailing NUL padding.
        self.assertEqual(clean_inline("Rules Summary\x00\x00\x00"), "Rules Summary")

    def test_clean_inline_strips_all_control(self):
        self.assertEqual(clean_inline("a\x07b\x1fc"), "abc")
        self.assertEqual(clean_inline("  spaced  "), "spaced")

    def test_clean_block_keeps_newlines_tabs(self):
        self.assertEqual(clean_block("line1\nline2\tend\x00"), "line1\nline2\tend")

    def test_clean_block_drops_other_control(self):
        self.assertEqual(clean_block("a\x0cb\x00c"), "abc")

    def test_empty(self):
        self.assertEqual(clean_inline(""), "")
        self.assertEqual(clean_block(""), "")

    def test_collapse_spaced_caps_fully_spaced(self):
        self.assertEqual(collapse_spaced_caps("C H A P T E R"), "CHAPTER")
        self.assertEqual(collapse_spaced_caps("F O U R"), "FOUR")
        self.assertEqual(
            collapse_spaced_caps("C H A P T E R  F O U R"), "CHAPTER FOUR"
        )

    def test_collapse_spaced_caps_leaves_two_letter_tokens(self):
        # 2-letter tokens are below the 3-letter threshold -> untouched. This is
        # also what protects "(A OR B)" and stat headers from being mangled.
        self.assertEqual(collapse_spaced_caps("US UK"), "US UK")
        self.assertEqual(collapse_spaced_caps("A OR B"), "A OR B")

    def test_collapse_spaced_caps_leaves_residual_split_forms(self):
        # KNOWN LIMITATION: partial kerning residue is NOT auto-corrected,
        # because a safe rule cannot tell "F URY" (artifact) from "A NEW" (real).
        self.assertEqual(collapse_spaced_caps("CHAPTER T WO"), "CHAPTER T WO")
        self.assertEqual(collapse_spaced_caps("PHILTRE OF F URY"), "PHILTRE OF F URY")

    def _chars(self, spec):
        # Helper: build (c, x0, x1) glyph tuples from a compact spec of
        # (char, x0, width); advances are explicit so gaps are exact.
        out = []
        for ch, x0, w in spec:
            out.append((ch, float(x0), float(x0 + w)))
        return out

    def test_split_glued_caps_by_gaps_inserts_word_boundary(self):
        # "ABHIT": gap before H is large (word boundary); others abut. size=20,
        # ratio 0.08 -> threshold 1.6. Boundary gap 5 > 1.6; intra gaps 0.
        chars = self._chars([
            ("A", 0, 10), ("B", 10, 10),
            ("H", 25, 10), ("I", 35, 10), ("T", 45, 10),
        ])
        self.assertEqual(
            split_glued_caps_by_gaps(chars, size=20.0, gap_ratio=0.08),
            {"ABHIT": "AB HIT"},
        )

    def test_split_glued_caps_by_gaps_ignores_tight_kerning(self):
        # All glyphs abut or slightly overlap (negative kerning) -> no split,
        # so a genuinely solid word like "BATTLEFIELD" is never broken up.
        chars = self._chars([
            ("W", 0, 10), ("O", 9.8, 10), ("R", 19.6, 10), ("D", 29.4, 10),
        ])
        self.assertEqual(split_glued_caps_by_gaps(chars, size=20.0), {})

    def test_split_glued_caps_by_gaps_resets_on_existing_space(self):
        # An existing space delimits tokens; only the glued token is mapped.
        chars = self._chars([
            ("M", 0, 10), ("A", 10, 10),
            ("W", 25, 10), ("O", 35, 10),
            (" ", 45, 5),
            ("R", 50, 10), ("X", 60, 10),
        ])
        self.assertEqual(
            split_glued_caps_by_gaps(chars, size=20.0, gap_ratio=0.08),
            {"MAWO": "MA WO"},
        )

    def test_apply_heading_space_map_only_touches_headings(self):
        mapping = {"RESOLVEHITS": "RESOLVE HITS", "MAKEWOUND": "MAKE WOUND"}
        text = (
            "## RESOLVEHITS\n"
            "## **1. MAKEWOUND ROLL**\n"
            "A body line mentioning RESOLVEHITS stays glued.\n"
            "### Already Spaced"
        )
        out = apply_heading_space_map(text, mapping)
        lines = out.split("\n")
        self.assertEqual(lines[0], "## RESOLVE HITS")
        self.assertEqual(lines[1], "## **1. MAKE WOUND ROLL**")
        # Body text is deliberately left untouched.
        self.assertIn("RESOLVEHITS stays glued", lines[2])
        self.assertEqual(lines[3], "### Already Spaced")

    def test_apply_heading_space_map_empty_is_noop(self):
        self.assertEqual(apply_heading_space_map("## RESOLVEHITS", {}), "## RESOLVEHITS")


# The DRM watermark the Frostgrave/Bolt Action PDFs stamped into the body.
_DRM = r"\*\*This ebook belongs to .*?\*\*"


class TestNormalizeBody(unittest.TestCase):
    def test_drops_full_line_boilerplate(self):
        text = "Real paragraph.\n\n**This ebook belongs to Tim (x@y.z), purchased 2026**\n\nMore."
        out = normalize_body(text, boilerplate_patterns=[_DRM], page_count=200)
        self.assertIn("Real paragraph.", out)
        self.assertIn("More.", out)
        self.assertNotIn("This ebook belongs to", out)

    def test_excises_boilerplate_fragment_in_table_cell(self):
        # The multiple-combats case: watermark fused into a real text cell.
        row = "|||eligible for a +2 modifer they cancel each<br>**This ebook belongs to Tim**||"
        out = normalize_body(row, boilerplate_patterns=[_DRM], page_count=200)
        self.assertIn("cancel each", out)
        self.assertNotIn("This ebook belongs to", out)
        self.assertTrue(out.lstrip().startswith("|"))  # still a table row

    def test_strips_standalone_page_number(self):
        text = "Body line.\n\n179\n\nNext body line."
        out = normalize_body(text, page_count=225)
        self.assertNotIn("\n179\n", f"\n{out}\n")
        self.assertIn("Body line.", out)
        self.assertIn("Next body line.", out)

    def test_strips_bold_page_number(self):
        self.assertEqual(normalize_body("**182**", page_count=225).strip(), "")

    def test_page_number_bound_by_page_count(self):
        # A standalone number larger than the document is real data, kept.
        self.assertEqual(normalize_body("500", page_count=225).strip(), "500")

    def test_page_number_toggle_off(self):
        self.assertEqual(
            normalize_body("179", strip_page_numbers=False, page_count=225).strip(),
            "179",
        )

    def test_keeps_single_cell_page_number_table_row(self):
        # A single-cell numeric table row is NOT deleted: it is indistinguishable
        # from a Bolt Action point subtotal, so we never remove it on a heuristic.
        table = (
            "|Thug|6|+2|Free|\n"
            "|---|---|---|---|\n"
            "|Apothecary|6|+1|75gc|\n"
            "||||||30|||||"
        )
        out = normalize_body(table, page_count=200)
        self.assertIn("||||||30|||||", out)
        self.assertIn("Apothecary", out)

    def test_keeps_subtotal_row(self):
        # The exact Bolt Action shape: a platoon subtotal in the points column.
        table = "|Sniper team|Reg|2||52|\n|||||504|"
        self.assertEqual(normalize_body(table, page_count=700).strip(), table)

    def test_keeps_all_empty_table_row_form(self):
        # An all-empty row is a blank character-sheet form field, not junk: kept.
        out = normalize_body("|A|B|\n|---|---|\n|1|2|\n|||", page_count=50)
        self.assertIn("|||", out)
        self.assertIn("|1|2|", out)

    def test_drops_table_row_emptied_by_boilerplate(self):
        # A row that was *only* boilerplate (we emptied it ourselves) is dropped.
        table = "|Name|Notes|\n|---|---|\n|Wolf|fast|\n|**This ebook belongs to Tim**||"
        out = normalize_body(table, boilerplate_patterns=[_DRM], page_count=200)
        self.assertIn("|Wolf|fast|", out)
        self.assertNotIn("This ebook belongs to", out)
        # the emptied row (-> `||`) is gone, not left as a stray empty row
        self.assertNotIn("\n||\n", f"\n{out}\n")

    def test_drops_excision_residue_line(self):
        # Watermark + picture-text marker + stray page number on one line ->
        # nothing but `187<br>` furniture remains -> drop, even with page-num off.
        marker = r"(?:<br>\s*)?\*\*-+ (?:Start|End) of picture text -+\*\*(?:<br>)?"
        line = "187<br>**This ebook belongs to Tim**<br>**----- End of picture text -----**<br>"
        text = f"Real prose.\n\n{line}\n\nMore prose."
        out = normalize_body(text, boilerplate_patterns=[_DRM, marker], strip_page_numbers=False)
        self.assertIn("Real prose.", out)
        self.assertIn("More prose.", out)
        self.assertNotIn("This ebook belongs to", out)
        self.assertNotIn("picture text", out)
        self.assertNotIn("187", out)

    def test_collapses_inline_double_space_from_excision(self):
        # Mid-sentence excision leaves a double space; collapse it (leading indent kept).
        text = "place five tokens.The **This ebook belongs to Tim** recovery of these."
        out = normalize_body(text, boilerplate_patterns=[_DRM], page_count=200)
        self.assertIn("tokens.The recovery of these.", out)

    def test_skips_fenced_code_block(self):
        # A page-number-looking line inside a code fence must be left untouched.
        text = "```\n179\n```"
        self.assertEqual(normalize_body(text, page_count=225), text)

    def test_idempotent(self):
        marker = r"(?:<br>\s*)?\*\*-+ (?:Start|End) of picture text -+\*\*(?:<br>)?"
        text = (
            "Intro.\n\n**This ebook belongs to Tim**\n\n"
            "|A|B|\n|---|---|\n|1|2|\n|||\n\n"
            "187<br>**----- End of picture text -----**<br>\n\nEnd."
        )
        once = normalize_body(text, boilerplate_patterns=[_DRM, marker], page_count=225)
        twice = normalize_body(once, boilerplate_patterns=[_DRM, marker], page_count=225)
        self.assertEqual(once, twice)

    def test_keeps_legitimate_table_and_separator(self):
        table = "|Bear|Bear|\n|---|---|\n|M|Notes|\n|6|Animal, Large|"
        out = normalize_body(table, page_count=225)
        self.assertEqual(out.strip(), table)  # untouched

    def test_keeps_data_row_with_small_numbers(self):
        # A stat row of several numbers is NOT a page-number row (>1 non-empty cell).
        row = "|6|+4|+0|12|+0|14|"
        self.assertEqual(normalize_body(row, page_count=225).strip(), row)

    def test_structural_caller_skips_normalization(self):
        # normalize_body is a pure helper; the 'structural' skip lives in extract.py.
        # Here we just assert that with no patterns + page numbers off, text is inert.
        text = "**This ebook belongs to Tim**\n\n179"
        self.assertEqual(
            normalize_body(text, boilerplate_patterns=[], strip_page_numbers=False),
            text,
        )

    def test_empty(self):
        self.assertEqual(normalize_body(""), "")

    def test_collapses_spaced_caps_chapter_heading(self):
        # The Frostgrave chapter-opener artifact (a markdown heading line).
        text = "## C H A P T E R  F O U R SPELLS"
        out = normalize_body(text, page_count=225)
        self.assertIn("## CHAPTER FOUR SPELLS", out)
        self.assertNotIn("C H A P T E R", out)

    def test_preserves_stat_table_single_letter_columns(self):
        # Necromunda stat header: "S T W I A" is a single-letter column run that
        # the spaced-caps regex matches but MUST NOT collapse (it is data, not a
        # spaced word). It is not a heading line, so it is left untouched.
        line = 'M WS BS S T W I A Ld Cl Wil Int 5" 5+ 5+ 3 3 1 4+ 1 7+ 8+ 9+ 9+'
        out = normalize_body(line, page_count=300)
        self.assertIn("S T W I A", out)
        self.assertNotIn("STWIA", out)

    def test_collapse_scoped_to_headings_only(self):
        # A heading collapses; an adjacent stat line in the body is preserved.
        text = "## C H A P T E R  S I X BESTIARY\n\nM WS BS S T W I A Ld Cl Wil Int"
        out = normalize_body(text, page_count=300)
        self.assertIn("## CHAPTER SIX BESTIARY", out)
        self.assertIn("S T W I A", out)

    def test_collapses_fully_spaced_but_leaves_residual_in_heading(self):
        # The fully-spaced "C H A P T E R" collapses; the kerning-fused "T WO"
        # residue is a documented limitation and is left for human review (a
        # safe auto-fix can't distinguish it from legitimate text).
        text = "## C H A P T E R  T WO PLAYING THE GAME"
        out = normalize_body(text, page_count=300)
        self.assertIn("## CHAPTER T WO PLAYING THE GAME", out)
        self.assertNotIn("C H A P T E R", out)

    def test_collapses_spaced_caps_preserves_fenced_code(self):
        # Code lines are not headings, so spaced caps inside a fence are left
        # untouched (also guarded by the in_code gate).
        code = "```\nA B C D E\n```"
        self.assertEqual(normalize_body(code, page_count=225), code)

    def test_collapse_spaced_caps_idempotent(self):
        text = "## C H A P T E R  F O U R SPELLS\n\n179\n\nBody."
        once = normalize_body(text, page_count=225)
        twice = normalize_body(once, page_count=225)
        self.assertEqual(once, twice)

    def test_collapses_blank_runs_from_removals(self):
        text = "A\n\n179\n\n180\n\nB"
        out = normalize_body(text, page_count=225)
        self.assertNotIn("\n\n\n", out)
        self.assertIn("A", out)
        self.assertIn("B", out)


class TestReformatStatProfiles(unittest.TestCase):
    HEADER_ROW = "| M | WS | BS | S | T | W | I | A | Ld | Cl | Wil | Int |"
    SEP_ROW = "|---|---|---|---|---|---|---|---|---|---|---|---|"

    def _table_rows(self, out):
        return [ln for ln in out.split("\n") if ln.startswith("|")]

    def test_runon_profile_with_name_and_cost(self):
        line = (
            "VAN SAAR PRIME (LEADER)......130 CREDITS "
            "M WS BS S T W I A Ld Cl Wil Int 4\" 4+ 2+ 3 3 2 5+ 2 4+ 5+ 5+ 4+"
        )
        out = reformat_stat_profiles(line)
        rows = self._table_rows(out)
        self.assertEqual(rows[0], self.HEADER_ROW)
        self.assertEqual(rows[1], self.SEP_ROW)
        self.assertEqual(
            rows[2], "| 4\" | 4+ | 2+ | 3 | 3 | 2 | 5+ | 2 | 4+ | 5+ | 5+ | 4+ |"
        )
        # Name/cost preserved above the table, dotted leader collapsed.
        self.assertIn("VAN SAAR PRIME (LEADER) 130 CREDITS", out)
        self.assertLess(out.index("VAN SAAR PRIME"), out.index(self.HEADER_ROW))

    def test_bold_header(self):
        line = (
            "GOLIATH BULLY (JUVE)....35 CREDITS EACH "
            "**M WS BS S T W I A Ld Cl Wil Int** 4\" 4+ 5+ 4 4 1 4+ 1 9+ 7+ 9+ 9+"
        )
        out = reformat_stat_profiles(line)
        rows = self._table_rows(out)
        self.assertEqual(rows[0], self.HEADER_ROW)
        self.assertEqual(
            rows[2], "| 4\" | 4+ | 5+ | 4 | 4 | 1 | 4+ | 1 | 9+ | 7+ | 9+ | 9+ |"
        )

    def test_br_separated_header_and_values_with_suffix(self):
        line = (
            "M WS BS S T W I A Ld Cl Wil Int<br>5\" 3+ - 3 3 1 4+ 1 8+ 6+ 8+ 8+"
            "<br>**----- End of picture text -----**<br>"
        )
        out = reformat_stat_profiles(line)
        rows = self._table_rows(out)
        self.assertEqual(rows[0], self.HEADER_ROW)
        # Dash value preserved in position 3 (BS).
        self.assertEqual(
            rows[2], "| 5\" | 3+ | - | 3 | 3 | 1 | 4+ | 1 | 8+ | 6+ | 8+ | 8+ |"
        )
        # Trailing picture-text becomes its own line below the table.
        self.assertIn("End of picture text", out)
        self.assertGreater(out.index("End of picture text"), out.index(rows[2]))

    def test_two_digit_target_numbers(self):
        line = "M WS BS S T W I A Ld Cl Wil Int - 4\" 3+ 4 4 2 6+ 2 8+ 6+ 7+ 11+"
        out = reformat_stat_profiles(line)
        rows = self._table_rows(out)
        self.assertEqual(
            rows[2], "| - | 4\" | 3+ | 4 | 4 | 2 | 6+ | 2 | 8+ | 6+ | 7+ | 11+ |"
        )

    def test_idempotent(self):
        line = (
            "VAN SAAR TEK (GANGER)....65 CREDITS "
            "M WS BS S T W I A Ld Cl Wil Int 4\" 4+ 3+ 3 3 1 5+ 1 6+ 7+ 7+ 6+"
        )
        once = reformat_stat_profiles(line)
        twice = reformat_stat_profiles(once)
        self.assertEqual(once, twice)

    def test_fewer_than_twelve_values_left_untouched(self):
        # Only 11 trailing values -> not a complete profile -> leave verbatim.
        line = "M WS BS S T W I A Ld Cl Wil Int 4\" 4+ 2+ 3 3 2 5+ 2 4+ 5+ 5+"
        self.assertEqual(reformat_stat_profiles(line), line)

    def test_prose_after_header_left_untouched(self):
        # Header-like tokens followed by prose, not values -> never split.
        line = "M WS BS S T W I A Ld Cl Wil Int are the twelve characteristics."
        self.assertEqual(reformat_stat_profiles(line), line)

    def test_existing_table_row_untouched(self):
        line = "| M | WS | BS | S | T | W | I | A | Ld | Cl | Wil | Int |"
        self.assertEqual(reformat_stat_profiles(line), line)

    def test_non_profile_text_unchanged(self):
        text = "Some rules paragraph.\n\nAnother line with no profile."
        self.assertEqual(reformat_stat_profiles(text), text)

    def test_emitted_table_passes_tables_gate(self):
        line = (
            "VAN SAAR PRIME (LEADER)......130 CREDITS "
            "M WS BS S T W I A Ld Cl Wil Int 4\" 4+ 2+ 3 3 2 5+ 2 4+ 5+ 5+ 4+"
        )
        out = reformat_stat_profiles(line)
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "s.md"), "w", encoding="utf-8") as fh:
                fh.write(out + "\n")
            fails: list = []
            verify_vault.check_tables(tmp, ["s.md"], fails)
            self.assertEqual(fails, [], f"emitted table tripped tables gate: {fails}")

    def test_fighter_header_pattern_unchanged(self):
        # Acceptance criterion: the generalized builder reproduces the original
        # hardcoded fighter header regex byte-for-byte, so the multi-profile
        # refactor is provably behavior-preserving for fighters.
        self.assertEqual(
            _profile_header(_FIGHTER_COLS).pattern,
            r"\*{0,2}\s*M\s+WS\s+BS\s+S\s+T\s+W\s+I\s+A\s+Ld\s+Cl\s+Wil\s+Int\s*\*{0,2}",
        )


class TestReformatEquipmentLists(unittest.TestCase):
    """Unit tests for reformat_equipment_lists (Necromunda equipment normalizer)."""

    def _table_rows(self, text):
        return [ln for ln in text.split("\n") if ln.startswith("|")]

    def test_simple_dotted_leader(self):
        inp = (
            "- Autogun......................... 15 credits\n"
            "- Boltgun.......................... 55 credits"
        )
        out = reformat_equipment_lists(inp)
        rows = self._table_rows(out)
        self.assertEqual(rows[0], "| Item | Cost |")
        self.assertIn("| Autogun | 15 credits |", rows)
        self.assertIn("| Boltgun | 55 credits |", rows)
        self.assertNotIn("...", out)

    def test_upgrade_sub_row(self):
        inp = (
            "- Boltgun.......................... 55 credits\n"
            "- Master-crafted .......+15 credits"
        )
        out = reformat_equipment_lists(inp)
        rows = self._table_rows(out)
        self.assertIn("| Boltgun | 55 credits |", rows)
        # Upgrade gets em-dash prefix.
        self.assertIn("| \u2014 Master-crafted | +15 credits |", rows)

    def test_inline_merge_split(self):
        # pymupdf4llm fuses two adjacent-column items onto one line.
        inp = "- Bolt pistol......................45 credits - Master-crafted .......+10 credits"
        out = reformat_equipment_lists(inp)
        rows = self._table_rows(out)
        self.assertIn("| Bolt pistol | 45 credits |", rows)
        self.assertIn("| \u2014 Master-crafted | +10 credits |", rows)
        self.assertEqual(len([r for r in rows if r.startswith("| Item")]), 1)

    def test_hota_bare_line_split(self):
        # Halls of the Ancients: two items on one bare (non-"- ") line.
        inp = "Ironhead autogun ........25 credits Ironhead boltgun .........95 credits"
        out = reformat_equipment_lists(inp)
        rows = self._table_rows(out)
        self.assertIn("| Ironhead autogun | 25 credits |", rows)
        self.assertIn("| Ironhead boltgun | 95 credits |", rows)

    def test_hota_continuation_join(self):
        # Halls of the Ancients: item name split mid-word across two "- " bullets.
        inp = (
            "- Ironhead heavy\n\n"
            "- flamer*.......................210 credits Ironhead heavy\n\n"
            "- stubber*.....................140 credits"
        )
        out = reformat_equipment_lists(inp)
        rows = self._table_rows(out)
        self.assertIn("| Ironhead heavy flamer* | 210 credits |", rows)
        self.assertIn("| Ironhead heavy stubber* | 140 credits |", rows)

    def test_narrative_bullet_not_tablified(self):
        # A bullet mentioning "credits" mid-sentence must never be tablified.
        inp = (
            "- 6-8 Scrap Shipment: The gang receives 2D6x10 credits worth of "
            "weapons and Wargear chosen from the list."
        )
        out = reformat_equipment_lists(inp)
        self.assertEqual(out.strip(), inp.strip())
        self.assertNotIn("|", out)

    def test_idempotent(self):
        inp = (
            "- Autogun......................... 15 credits\n"
            "- Boltgun.......................... 55 credits\n"
            "- Master-crafted .......+15 credits"
        )
        once = reformat_equipment_lists(inp)
        twice = reformat_equipment_lists(once)
        self.assertEqual(once, twice)

    def test_no_credits_returns_unchanged(self):
        inp = "Some text without the magic word.\n\nAnother paragraph."
        self.assertEqual(reformat_equipment_lists(inp), inp)

    def test_existing_table_row_untouched(self):
        inp = "| Item | Cost |\n|---|---|\n| Autogun | 15 credits |"
        out = reformat_equipment_lists(inp)
        self.assertEqual(out.strip(), inp.strip())

    def test_emitted_table_passes_tables_gate(self):
        inp = (
            "- Autogun......................... 15 credits\n"
            "- Boltgun.......................... 55 credits\n"
            "- Master-crafted .......+15 credits"
        )
        out = reformat_equipment_lists(inp)
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "s.md"), "w", encoding="utf-8") as fh:
                fh.write(out + "\n")
            fails: list = []
            verify_vault.check_tables(tmp, ["s.md"], fails)
            self.assertEqual(fails, [], f"emitted table tripped tables gate: {fails}")


class TestReformatVehicleProfiles(unittest.TestCase):
    # Necromunda vehicle profile: M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int.
    HEADER_ROW = "| M | Front | Side | Rear | HP | Hnd | Sv | BS | Ld | Cl | Wil | Int |"
    SEP_ROW = "|---|---|---|---|---|---|---|---|---|---|---|---|"

    def _table_rows(self, out):
        return [ln for ln in out.split("\n") if ln.startswith("|")]

    def test_runon_vehicle_profile_with_name_and_cost(self):
        line = (
            "CARGO-8 RIDGEHAULER......280 CREDITS "
            'M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int 4" 6 5 5 5 7+ 4+ 5+ 7+ 6+ 8+ 9+'
        )
        out = reformat_stat_profiles(line)
        rows = self._table_rows(out)
        self.assertEqual(rows[0], self.HEADER_ROW)
        self.assertEqual(rows[1], self.SEP_ROW)
        self.assertEqual(
            rows[2], '| 4" | 6 | 5 | 5 | 5 | 7+ | 4+ | 5+ | 7+ | 6+ | 8+ | 9+ |'
        )
        self.assertIn("CARGO-8 RIDGEHAULER 280 CREDITS", out)
        self.assertLess(out.index("CARGO-8 RIDGEHAULER"), out.index(self.HEADER_ROW))

    def test_bold_vehicle_header(self):
        line = (
            "RIDGERUNNER....130 CREDITS "
            '**M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int** 7" 5 4 4 3 6+ 5+ 4+ 7+ 7+ 8+ 8+'
        )
        out = reformat_stat_profiles(line)
        rows = self._table_rows(out)
        self.assertEqual(rows[0], self.HEADER_ROW)
        self.assertEqual(
            rows[2], '| 7" | 5 | 4 | 4 | 3 | 6+ | 5+ | 4+ | 7+ | 7+ | 8+ | 8+ |'
        )

    def test_vehicle_dash_value_preserved(self):
        # A vehicle with no BS (crewless / remote) renders BS as '-'.
        line = 'M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int 5" 7 6 6 4 8+ 5+ - 8+ 7+ 9+ 9+'
        out = reformat_stat_profiles(line)
        rows = self._table_rows(out)
        self.assertEqual(
            rows[2], '| 5" | 7 | 6 | 6 | 4 | 8+ | 5+ | - | 8+ | 7+ | 9+ | 9+ |'
        )

    def test_vehicle_idempotent(self):
        line = (
            "WOLFQUAD....95 CREDITS "
            'M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int 8" 4 4 3 2 5+ 5+ 4+ 7+ 7+ 8+ 8+'
        )
        once = reformat_stat_profiles(line)
        twice = reformat_stat_profiles(once)
        self.assertEqual(once, twice)

    def test_vehicle_fewer_than_twelve_values_left_untouched(self):
        # 11 trailing values -> incomplete profile -> verbatim (safe failure).
        line = 'M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int 4" 6 5 5 5 7+ 4+ 5+ 7+ 6+ 8+'
        self.assertEqual(reformat_stat_profiles(line), line)

    def test_existing_vehicle_table_row_untouched(self):
        line = "| M | Front | Side | Rear | HP | Hnd | Sv | BS | Ld | Cl | Wil | Int |"
        self.assertEqual(reformat_stat_profiles(line), line)

    def test_mixed_fighter_and_vehicle_both_tabled(self):
        # Common case: a vehicle profile and its crew (fighter) profile together.
        text = (
            "RIDGERUNNER....130 CREDITS "
            'M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int 7" 5 4 4 3 6+ 5+ 4+ 7+ 7+ 8+ 8+\n'
            "CREW (CHAMPION)....0 CREDITS "
            'M WS BS S T W I A Ld Cl Wil Int 5" 4+ 3+ 3 3 1 4+ 1 7+ 6+ 7+ 7+'
        )
        out = reformat_stat_profiles(text)
        self.assertIn(self.HEADER_ROW, out)  # vehicle header
        self.assertIn(
            "| M | WS | BS | S | T | W | I | A | Ld | Cl | Wil | Int |", out
        )  # fighter header
        self.assertEqual(
            out.count("|---|---|---|---|---|---|---|---|---|---|---|---|"), 2
        )

    def test_emitted_vehicle_table_passes_tables_gate(self):
        line = (
            "CARGO-8 RIDGEHAULER......280 CREDITS "
            'M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int 4" 6 5 5 5 7+ 4+ 5+ 7+ 6+ 8+ 9+'
        )
        out = reformat_stat_profiles(line)
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "v.md"), "w", encoding="utf-8") as fh:
                fh.write(out + "\n")
            fails: list = []
            verify_vault.check_tables(tmp, ["v.md"], fails)
            self.assertEqual(fails, [], f"emitted vehicle table tripped tables gate: {fails}")


class TestMergeWrappedTableRows(unittest.TestCase):
    @staticmethod
    def _row(cells):
        """Build a markdown row from explicit cells (guarantees column count)."""
        return "|" + "|".join(cells) + "|"

    def _table(self, rows):
        return "\n".join(self._row(r) for r in rows)

    # 10-column house weaponry chart: Weapon S L S L Str Ap D Am Traits.
    def _house(self):
        return self._table(
            [
                ["", "Rng", "Rng", "Acc", "Acc", "", "", "", "", ""],
                ["---"] * 10,
                ["Weapon", "S", "L", "S", "L", "Str", "Ap", "D", "Am", "Traits"],
                ["- frag grenades", '6"', '24"', "-1", "-", "3", "-", "1", "6+",
                 'Blast (3"), Knockback,'],
                [""] * 9 + ["Rapid Fire (1), Unstable"],
                ["- krak grenades", '6"', '24"', "-1", "-", "6", "-2", "2", "6+", "-"],
            ]
        )

    def _rows(self, out):
        return [ln for ln in out.split("\n") if ln.startswith("|")]

    def test_house_chart_continuation_merged(self):
        out = merge_wrapped_table_rows(self._house())
        rows = self._rows(out)
        self.assertEqual(len(rows), 5)  # 6 rows -> continuation dropped
        self.assertIn(
            self._row(
                ["- frag grenades", '6"', '24"', "-1", "-", "3", "-", "1", "6+",
                 'Blast (3"), Knockback, Rapid Fire (1), Unstable']
            ),
            rows,
        )
        self.assertNotIn(self._row([""] * 9 + ["Rapid Fire (1), Unstable"]), out)

    def test_trading_post_12col_with_al_cost(self):
        text = self._table(
            [
                ["", "Range", "Range", "Accuracy", "Accuracy", "", "", "", "", "", "", "Credit"],
                ["---"] * 12,
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits", "AL", "Cost"],
                ["Arc rife", '9"', '24"', "+2", "-1", "5", "-", "1", "6+",
                 "Blaze, Rapid Fire (1),", "R13", "100"],
                [""] * 9 + ["Shock", "", ""],
                ["Autogun", '8"', '24"', "+1", "-", "3", "-", "1", "4+",
                 "Rapid Fire (1)", "C", "15"],
            ]
        )
        out = merge_wrapped_table_rows(text)
        self.assertIn(
            self._row(
                ["Arc rife", '9"', '24"', "+2", "-1", "5", "-", "1", "6+",
                 "Blaze, Rapid Fire (1), Shock", "R13", "100"]
            ),
            out,
        )
        self.assertNotIn(self._row([""] * 9 + ["Shock", "", ""]), out)

    def test_chained_three_line_wrap(self):
        text = self._table(
            [
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits", "AL", "Cost"],
                ["---"] * 12,
                ["Big gun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Alpha,", "C", "15"],
                [""] * 9 + ["Beta,", "", ""],
                [""] * 9 + ["Gamma", "", ""],
            ]
        )
        out = merge_wrapped_table_rows(text)
        rows = self._rows(out)
        self.assertEqual(len(rows), 3)  # header, sep, single merged data row
        self.assertIn(
            self._row(
                ["Big gun", '8"', '24"', "+1", "-", "3", "-", "1", "4+",
                 "Alpha, Beta, Gamma", "C", "15"]
            ),
            out,
        )

    def test_not_merged_when_prior_lacks_trailing_comma(self):
        text = self._table(
            [
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits", "AL", "Cost"],
                ["---"] * 12,
                ["Gun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Rapid Fire (1)", "C", "15"],
                [""] * 9 + ["Stray text", "", ""],
            ]
        )
        self.assertEqual(merge_wrapped_table_rows(text), text)

    def test_subtotal_row_untouched(self):
        text = self._table(
            [
                ["Item", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits", "AL", "Cost"],
                ["---"] * 12,
                ["Gun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Rapid Fire (1),", "C", "15"],
                [""] * 11 + ["504"],  # value in Cost column, not Traits
            ]
        )
        self.assertEqual(merge_wrapped_table_rows(text), text)

    def test_name_wrap_row_untouched(self):
        text = self._table(
            [
                ["Weapon", "S", "L", "S", "L", "Str", "Ap", "D", "Am", "Traits"],
                ["---"] * 10,
                ["Assault grenade"] + [""] * 9,
                ["launchers (twin-linked)"] + [""] * 9,
            ]
        )
        self.assertEqual(merge_wrapped_table_rows(text), text)

    def test_table_without_traits_column_untouched(self):
        text = self._table(
            [
                ["M", "WS", "BS", "S", "T", "W", "I", "A", "Ld", "Cl", "Wil", "Int"],
                ["---"] * 12,
                ['4"', "4+", "2+", "3", "3", "2", "5+", "2", "4+", "5+", "5+", "4+"],
            ]
        )
        self.assertEqual(merge_wrapped_table_rows(text), text)

    def test_small_table_with_traits_header_untouched(self):
        # < 6 columns: block guard prevents action even with a Traits column.
        text = self._table(
            [
                ["Name", "Traits"],
                ["---", "---"],
                ["Knife", "Melee,"],
                ["", "Silent"],
            ]
        )
        self.assertEqual(merge_wrapped_table_rows(text), text)

    # Mid-trait wrap: the Trading Post splits "Shield Breaker" across rows as
    # "...Knockback, Shield" + "Breaker, Shock" -- no trailing comma, so only the
    # _MULTIWORD_TRAITS allowlist can rejoin it. Mirrors the real static-round
    # rows in necromunda-core-rulebook-2023 / 1.59 Trading Post.
    def _shield_breaker(self):
        return self._table(
            [
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits", "AL", "Cost"],
                ["---"] * 12,
                ["- static round", '6"', '12"', "+2", "-", "3", "-", "1", "",
                 "4+ Limited, Knockback, Shield", "I9", "+10"],
                [""] * 9 + ["Breaker, Shock", "", ""],
                ["- warp round", '6"', '12"', "+2", "-", "3", "-", "1", "",
                 "4+ Cursed, Limited, Single Shot", "I10", "+15"],
            ]
        )

    def test_mid_trait_wrap_shield_breaker_merged(self):
        out = merge_wrapped_table_rows(self._shield_breaker())
        self.assertIn(
            self._row(
                ["- static round", '6"', '12"', "+2", "-", "3", "-", "1", "",
                 "4+ Limited, Knockback, Shield Breaker, Shock", "I9", "+10"]
            ),
            out,
        )
        self.assertNotIn(self._row([""] * 9 + ["Breaker, Shock", "", ""]), out)

    def test_mid_trait_wrap_idempotent(self):
        once = merge_wrapped_table_rows(self._shield_breaker())
        twice = merge_wrapped_table_rows(once)
        self.assertEqual(once, twice)

    def test_mid_trait_unknown_phrase_not_merged(self):
        # prev ends "Shield", continuation starts "Wall" -> "Shield Wall" is not a
        # real trait, so the allowlist must NOT merge it.
        text = self._table(
            [
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits", "AL", "Cost"],
                ["---"] * 12,
                ["Gun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Knockback, Shield", "C", "15"],
                [""] * 9 + ["Wall, Shock", "", ""],
            ]
        )
        self.assertEqual(merge_wrapped_table_rows(text), text)

    def test_idempotent(self):
        once = merge_wrapped_table_rows(self._house())
        twice = merge_wrapped_table_rows(once)
        self.assertEqual(once, twice)

    def test_non_table_text_unchanged(self):
        text = "Some prose.\n\nMore prose, with a comma."
        self.assertEqual(merge_wrapped_table_rows(text), text)

    def test_merged_table_passes_tables_gate(self):
        out = merge_wrapped_table_rows(self._house())
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "w.md"), "w", encoding="utf-8") as fh:
                fh.write(out + "\n")
            fails: list = []
            verify_vault.check_tables(tmp, ["w.md"], fails)
            self.assertEqual(fails, [], f"merged table tripped tables gate: {fails}")


class TestLigatureCellFix(unittest.TestCase):
    """Regression guard for extract._ligature_cell_fix -- the workaround for
    pymupdf4llm dropping zero-width ligature glyphs in table cells (the spike's
    'fighter' -> 'fghter'). We assert the patch's contract on the real
    pymupdf4llm helper rather than re-running a full PDF extraction."""

    def _load(self):
        try:
            import extract as _extract
            from pymupdf4llm.helpers import utils as _utils
        except Exception as exc:  # pragma: no cover - env without pymupdf4llm
            self.skipTest(f"pymupdf4llm not importable: {exc}")
        return _extract, _utils

    def test_zero_width_char_inside_cell_is_kept(self):
        extract, utils = self._load()
        cell = (0.0, 0.0, 100.0, 20.0)
        zero_width = (10.0, 5.0, 10.0, 15.0)  # x0 == x1 -> zero area, origin inside
        # Unpatched, pymupdf4llm drops it (0 overlap of a 0-area box).
        self.assertFalse(utils.almost_in_bbox(zero_width, cell, portion=0.5))
        with extract._ligature_cell_fix(True):
            self.assertTrue(utils.almost_in_bbox(zero_width, cell, portion=0.5))
        # Restored on exit (process stays pure).
        self.assertFalse(utils.almost_in_bbox(zero_width, cell, portion=0.5))

    def test_zero_width_char_outside_cell_not_kept(self):
        extract, utils = self._load()
        cell = (0.0, 0.0, 100.0, 20.0)
        outside = (200.0, 5.0, 200.0, 15.0)  # zero area but origin far outside
        with extract._ligature_cell_fix(True):
            self.assertFalse(utils.almost_in_bbox(outside, cell, portion=0.5))

    def test_normal_char_delegates_to_original(self):
        extract, utils = self._load()
        cell = (0.0, 0.0, 100.0, 20.0)
        inside = (10.0, 5.0, 18.0, 15.0)      # normal-width glyph well inside
        disjoint = (200.0, 5.0, 210.0, 15.0)  # normal-width glyph outside
        with extract._ligature_cell_fix(True):
            self.assertTrue(utils.almost_in_bbox(inside, cell, portion=0.5))
            self.assertFalse(utils.almost_in_bbox(disjoint, cell, portion=0.5))

    def test_disabled_is_noop(self):
        extract, utils = self._load()
        orig = utils.almost_in_bbox
        with extract._ligature_cell_fix(False):
            self.assertIs(utils.almost_in_bbox, orig)
        self.assertIs(utils.almost_in_bbox, orig)


def _trow(cells):
    """Build a markdown table row from explicit cells (guarantees column count)."""
    return "|" + "|".join(cells) + "|"


def _ttable(rows):
    return "\n".join(_trow(r) for r in rows)


def _table_lines(out):
    return [ln for ln in out.split("\n") if ln.startswith("|")]


def _passes_tables_gate(test, md):
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "w.md"), "w", encoding="utf-8") as fh:
            fh.write(md + "\n")
        fails: list = []
        verify_vault.check_tables(tmp, ["w.md"], fails)
        test.assertEqual(fails, [], f"table tripped the tables gate: {fails}")


class TestTableGuard(unittest.TestCase):
    """lib.table_guard.data_drift: data-row token multiset is the invariant."""

    def _simple(self):
        return _ttable(
            [
                ["Weapon", "S", "L", "Str", "AP", "D"],
                ["---"] * 6,
                ["Gun", '8"', '24"', "3", "-", "1"],
                ["Knife", "-", "-", "3", "-", "1"],
            ]
        )

    def test_identical_is_clean(self):
        t = self._simple()
        self.assertEqual(table_guard.data_drift(t, t), [])

    def test_header_relabel_is_clean(self):
        # Header region is exempt: renaming a header column is not drift.
        before = self._simple()
        after = before.replace("|Weapon|S|L|Str|AP|D|", "|Weapon|Range (S)|Range (L)|Str|AP|D|")
        self.assertNotEqual(before, after)
        self.assertEqual(table_guard.data_drift(before, after), [])

    def test_row_merge_is_clean(self):
        before = _ttable(
            [
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits", "AL", "Cost"],
                ["---"] * 12,
                ["Arc rifle", '9"', '24"', "+2", "-1", "5", "-", "1", "6+",
                 "Blaze, Rapid Fire (1),", "R13", "100"],
                [""] * 9 + ["Shock", "", ""],
            ]
        )
        after = merge_wrapped_table_rows(before)
        self.assertNotEqual(before, after)
        self.assertEqual(table_guard.data_drift(before, after), [])

    def test_added_token_flagged(self):
        before = self._simple()
        after = before.replace("|Gun|8\"|24\"|3|-|1|", "|Gun|8\"|24\"|3|-|1 EXTRA|")
        drift = table_guard.data_drift(before, after)
        self.assertTrue(drift)
        self.assertIn("added", " ".join(drift))
        self.assertIn("EXTRA", " ".join(drift))

    def test_dropped_token_flagged(self):
        before = _ttable(
            [
                ["Weapon", "S", "L", "Str", "AP", "D"],
                ["---"] * 6,
                ["Gun", '8"', '24"', "3", "-", "1 Rapid"],
            ]
        )
        after = _ttable(
            [
                ["Weapon", "S", "L", "Str", "AP", "D"],
                ["---"] * 6,
                ["Gun", '8"', '24"', "3", "-", "1"],
            ]
        )
        drift = table_guard.data_drift(before, after)
        self.assertTrue(drift)
        self.assertIn("dropped", " ".join(drift))
        self.assertIn("Rapid", " ".join(drift))

    def test_changed_value_flagged(self):
        before = self._simple()
        after = before.replace("|Gun|8\"|24\"|3|-|1|", "|Gun|8\"|24\"|4|-|1|")
        drift = table_guard.data_drift(before, after)
        self.assertTrue(drift)
        joined = " ".join(drift)
        self.assertIn("dropped", joined)
        self.assertIn("added", joined)

    def test_table_count_mismatch_flagged(self):
        before = self._simple()
        after = before + "\n\n" + self._simple()
        drift = table_guard.data_drift(before, after)
        self.assertTrue(drift)
        self.assertIn("table count changed", " ".join(drift))

    def test_fenced_code_table_ignored(self):
        # A "table" inside a fenced code block is not a table; changing it is not
        # flagged (the guard, like verify_vault, is fenced-code aware).
        before = "```\n| not | a | table |\n```\n"
        after = "```\n| also | different |\n```\n"
        self.assertEqual(table_guard.data_drift(before, after), [])


class TestTableGuardStrict(unittest.TestCase):
    """lib.table_guard.data_drift_strict: the data region's ORDERED token
    sequence is the invariant (catches reordering the multiset guard misses)."""

    def _simple(self):
        return _ttable(
            [
                ["Weapon", "S", "L", "Str", "AP", "D"],
                ["---"] * 6,
                ["Gun", '8"', '24"', "3", "-", "1"],
                ["Knife", "-", "-", "3", "-", "1"],
            ]
        )

    def test_identical_is_clean(self):
        t = self._simple()
        self.assertEqual(table_guard.data_drift_strict(t, t), [])

    def test_row_swap_rejected_but_multiset_clean(self):
        before = self._simple()
        after = _ttable(
            [
                ["Weapon", "S", "L", "Str", "AP", "D"],
                ["---"] * 6,
                ["Knife", "-", "-", "3", "-", "1"],  # rows swapped
                ["Gun", '8"', '24"', "3", "-", "1"],
            ]
        )
        self.assertNotEqual(before, after)
        # the loose multiset guard cannot see a pure reorder ...
        self.assertEqual(table_guard.data_drift(before, after), [])
        # ... but the strict ordered-sequence guard does.
        drift = table_guard.data_drift_strict(before, after)
        self.assertTrue(drift)
        self.assertIn("order changed", " ".join(drift))

    def test_row_merge_is_clean(self):
        # Boundary-only edit: a wrapped continuation folded into its row keeps
        # linear token order, so strict permits it (the repairs the skill makes).
        before = _ttable(
            [
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits", "AL", "Cost"],
                ["---"] * 12,
                ["Arc rifle", '9"', '24"', "+2", "-1", "5", "-", "1", "6+",
                 "Blaze, Rapid Fire (1),", "R13", "100"],
                [""] * 9 + ["Shock", "", ""],
            ]
        )
        after = merge_wrapped_table_rows(before)
        self.assertNotEqual(before, after)
        self.assertEqual(table_guard.data_drift_strict(before, after), [])

    def test_added_token_flagged(self):
        before = self._simple()
        after = before.replace("|Gun|8\"|24\"|3|-|1|", "|Gun|8\"|24\"|3|-|1 EXTRA|")
        drift = table_guard.data_drift_strict(before, after)
        self.assertTrue(drift)

    def test_table_count_mismatch_flagged(self):
        before = self._simple()
        after = before + "\n\n" + self._simple()
        drift = table_guard.data_drift_strict(before, after)
        self.assertTrue(drift)
        self.assertIn("table count changed", " ".join(drift))


class TestIndexGuard(unittest.TestCase):
    """lib.index_guard.data_drift: ordered word/page token sequence across
    non-heading lines. De-gluing OK; page-swap / add / drop rejected."""

    def test_deglue_is_clean(self):
        before = "- Axe 5 Bow 9"
        after = "- Axe 5\n- Bow 9"
        self.assertEqual(index_guard.data_drift(before, after), [])

    def test_deglue_drops_dotted_leaders_clean(self):
        before = "- Action phase................99"
        after = "- Action phase 99"
        self.assertEqual(index_guard.data_drift(before, after), [])

    def test_added_letter_headings_are_ignored(self):
        # Re-grouping under `### A` / `### B` headers changes no entry tokens.
        before = "- Axe 5\n- Bow 9"
        after = "### A\n- Axe 5\n\n### B\n- Bow 9"
        self.assertEqual(index_guard.data_drift(before, after), [])

    def test_page_swap_rejected(self):
        # The failure a flat multiset would miss: same tokens, different meaning.
        before = "- Axe 5\n- Bow 9"
        after = "- Axe 9\n- Bow 5"
        drift = index_guard.data_drift(before, after)
        self.assertTrue(drift)
        self.assertIn("order changed", " ".join(drift))

    def test_dropped_page_rejected(self):
        before = "- Axe 5, 9"
        after = "- Axe 5"
        drift = index_guard.data_drift(before, after)
        self.assertTrue(drift)

    def test_wikilinked_pages_tokenize_as_their_alias(self):
        # A linkified index (build output) and its plain source are equivalent.
        plain = "- Movement 74\n- Crossing 75"
        linked = (
            "- Movement [[book/01-movement#MOVEMENT|74]]\n"
            "- Crossing [[book/01-movement|75]]"
        )
        self.assertEqual(index_guard.data_drift(plain, linked), [])

    def test_a_to_z_resort_is_rejected(self):
        # Documented: true reordering is out of scope; the guard rejects it.
        before = "- Bow 9\n- Axe 5"
        after = "- Axe 5\n- Bow 9"
        self.assertTrue(index_guard.data_drift(before, after))


class TestApplyEnrichment(unittest.TestCase):
    """apply_enrichment: machine-rendered summary + appended tags, safe-write."""

    def _note(self, **over):
        meta = {
            "title": "1.1 Background",
            "source": "book.pdf",
            "source_pages": [1, 2],
            "toc_level": 2,
            "toc_number": "01.01",
            "tags": ["pdf-import", "book"],
            "created": "2026-06-27",
            "generated_by": "p2v",
        }
        meta.update(over)
        return frontmatter.render_note(meta, "# Body\n\ncontent")

    def test_apply_sets_summary_and_appends_tags(self):
        meta, _ = frontmatter.split(self._note())
        updated, msg = apply_enrichment.apply(
            meta, "  a  faithful\nsummary ", ["topic/melee", "enriched"], force=False
        )
        self.assertEqual(msg, "applied")
        self.assertEqual(updated["summary"], "a faithful summary")  # whitespace collapsed
        self.assertEqual(updated["tags"], ["pdf-import", "book", "topic/melee", "enriched"])

    def test_apply_is_idempotent_without_force(self):
        meta, _ = frontmatter.split(self._note(summary="existing"))
        updated, msg = apply_enrichment.apply(meta, "new", [], force=False)
        self.assertIsNone(updated)
        self.assertIn("already enriched", msg)

    def test_apply_force_overwrites(self):
        meta, _ = frontmatter.split(self._note(summary="existing"))
        updated, _msg = apply_enrichment.apply(meta, "new", [], force=True)
        self.assertEqual(updated["summary"], "new")

    def test_appended_tags_are_deduped(self):
        meta, _ = frontmatter.split(self._note())
        updated, _msg = apply_enrichment.apply(meta, None, ["book", "enriched", "enriched"], False)
        self.assertEqual(updated["tags"], ["pdf-import", "book", "enriched"])

    def test_cli_refuses_non_p2v_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = os.path.join(tmp, "user.md")
            with open(note, "w", encoding="utf-8") as fh:
                fh.write("---\ntitle: mine\n---\n\nbody\n")  # no generated_by
            argv = sys.argv
            sys.argv = ["apply_enrichment.py", note, "--summary", "x"]
            try:
                rc = apply_enrichment.main()
            finally:
                sys.argv = argv
            self.assertEqual(rc, 1)
            with open(note, encoding="utf-8") as fh:
                self.assertNotIn("summary:", fh.read())  # untouched

    def test_cli_writes_summary_after_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = os.path.join(tmp, "n.md")
            with open(note, "w", encoding="utf-8") as fh:
                fh.write(self._note())
            argv = sys.argv
            sys.argv = ["apply_enrichment.py", note, "--summary", "hello",
                        "--add-tags", "topic/x,enriched"]
            try:
                rc = apply_enrichment.main()
            finally:
                sys.argv = argv
            self.assertEqual(rc, 0)
            out = open(note, encoding="utf-8").read()
            meta, _ = frontmatter.split(out)
            self.assertEqual(meta["summary"], "hello")
            self.assertIn("topic/x", meta["tags"])
            self.assertIn("enriched", meta["tags"])
            # summary rendered after tags, before created (KEY_ORDER)
            self.assertLess(out.index("tags:"), out.index("summary:"))
            self.assertLess(out.index("summary:"), out.index("created:"))


class TestApplyRepair(unittest.TestCase):
    """apply_repair: guard-gated, safe-write body repair. --kind table also
    forbids any change to non-table lines (whole-note layout-only)."""

    def _note(self, body, generated=True):
        meta = {
            "title": "1.1 Weapons",
            "source": "book.pdf",
            "source_pages": [1, 2],
            "toc_level": 2,
            "toc_number": "01.01",
            "tags": ["pdf-import", "book"],
            "created": "2026-06-27",
            "generated_by": "p2v",
        }
        if not generated:
            del meta["generated_by"]
        return frontmatter.render_note(meta, body)

    def _table(self, header="|Weapon|S|L|Str|AP|D|"):
        return (
            "Intro prose.\n\n"
            + header + "\n"
            "|---|---|---|---|---|---|\n"
            "|Gun|8\"|24\"|3|-|1|\n\n"
            "Trailing prose."
        )

    # ---- check() (pure) ----
    def test_check_table_header_relabel_clean(self):
        old = self._table()
        new = self._table("|Weapon|Range (S)|Range (L)|Str|AP|D|")  # header exempt
        self.assertEqual(apply_repair.check(old, new, "table"), [])

    def test_check_table_data_drift_flagged(self):
        old = self._table()
        new = old.replace("|Gun|8\"|24\"|3|-|1|", "|Gun|8\"|24\"|4|-|1|")
        self.assertTrue(apply_repair.check(old, new, "table"))

    def test_check_prose_change_flagged_even_if_table_identical(self):
        old = self._table()
        new = old.replace("Trailing prose.", "Trailing prose EDITED.")
        drift = apply_repair.check(old, new, "table")
        self.assertTrue(drift)
        self.assertIn("non-table content changed", " ".join(drift))

    def test_check_index_deglue_clean_swap_flagged(self):
        self.assertEqual(
            apply_repair.check("## Index\n\n- Axe 5 Bow 9", "## Index\n\n- Axe 5\n- Bow 9", "index"),
            [],
        )
        self.assertTrue(
            apply_repair.check("- Axe 5\n- Bow 9", "- Axe 9\n- Bow 5", "index")
        )

    # ---- CLI ----
    def _run(self, note_path, new_body, kind="table"):
        with tempfile.TemporaryDirectory() as tmp:
            nb = os.path.join(tmp, "new.md")
            with open(nb, "w", encoding="utf-8") as fh:
                fh.write(new_body)
            argv = sys.argv
            sys.argv = ["apply_repair.py", note_path, "--kind", kind, "--new-body", nb]
            try:
                return apply_repair.main()
            finally:
                sys.argv = argv

    def test_cli_applies_clean_reformat_preserving_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = os.path.join(tmp, "n.md")
            with open(note, "w", encoding="utf-8") as fh:
                fh.write(self._note(self._table()))
            new_body = self._table("|Weapon|Range (S)|Range (L)|Str|AP|D|")
            rc = self._run(note, new_body)
            self.assertEqual(rc, 0)
            with open(note, encoding="utf-8") as fh:
                meta, body = frontmatter.split(fh.read())
            self.assertEqual(meta["generated_by"], "p2v")  # frontmatter preserved
            self.assertIn("Range (S)", body)

    def test_cli_refuses_non_p2v_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = os.path.join(tmp, "user.md")
            with open(note, "w", encoding="utf-8") as fh:
                fh.write(self._note(self._table(), generated=False))
            rc = self._run(note, self._table("|Weapon|Range (S)|Range (L)|Str|AP|D|"))
            self.assertEqual(rc, 1)

    def test_cli_rejects_drift_and_leaves_note_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = os.path.join(tmp, "n.md")
            original = self._note(self._table())
            with open(note, "w", encoding="utf-8") as fh:
                fh.write(original)
            bad = self._table().replace("Trailing prose.", "Trailing prose EDITED.")
            rc = self._run(note, bad)
            self.assertEqual(rc, 1)
            with open(note, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), original)  # untouched


class TestPromoteHeaderBelowSeparator(unittest.TestCase):
    """The `group-row | separator | label-row` fix: pymupdf4llm pushes the real
    weapon-chart header below the separator, under a near-empty spanning row."""

    def _demoted(self):
        return _ttable(
            [
                ["", "Rng", "Rng", "Acc", "Acc", "", "", "", "", ""],
                ["---"] * 10,
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits"],
                ["Autogun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Rapid Fire (1)"],
                ["Lasgun", '18"', '24"', "+1", "-", "3", "-", "1", "2+", "Plentiful"],
            ]
        )

    def _demoted_fused(self):
        # Trading Post variant: 11 cols, fused `Am Traits`, `Credit` group label.
        return _ttable(
            [
                ["", "Range", "Range", "Accuracy", "Accuracy", "", "", "", "", "", "Credit"],
                ["---"] * 11,
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am Traits", "AL", "Cost"],
                ["Autopistol", '4"', '12"', "+1", "-", "3", "-", "1",
                 "4+ Rapid Fire (1), Sidearm", "C", "10"],
            ]
        )

    def test_header_promoted_and_merged(self):
        out = promote_header_below_separator(self._demoted())
        rows = _table_lines(out)
        self.assertEqual(len(rows), 4)  # group+label folded into one header row
        self.assertEqual(
            rows[0],
            _trow(["Weapon", "Rng (S)", "Rng (L)", "Acc (S)", "Acc (L)",
                   "S", "AP", "D", "Am", "Traits"]),
        )
        # separator now sits directly under the real header (index 1).
        self.assertTrue(rows[1].startswith("|---"))
        # data rows preserved verbatim.
        self.assertIn(
            _trow(["Autogun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Rapid Fire (1)"]),
            rows,
        )

    def test_guard_clean(self):
        before = self._demoted()
        after = promote_header_below_separator(before)
        self.assertNotEqual(before, after)
        # The demoted label row is exempt in `before`, so relocating it is not drift.
        self.assertEqual(table_guard.data_drift(before, after), [])

    def test_promote_then_split_renders_and_guard_clean(self):
        before = self._demoted_fused()
        after = split_am_traits(promote_header_below_separator(before))
        rows = _table_lines(after)
        # Header is real, Am/Traits split, Credit (Cost) merged.
        self.assertEqual(
            rows[0],
            _trow(["Weapon", "Range (S)", "Range (L)", "Accuracy (S)", "Accuracy (L)",
                   "S", "AP", "D", "Am", "Traits", "AL", "Credit (Cost)"]),
        )
        self.assertIn(
            _trow(["Autopistol", '4"', '12"', "+1", "-", "3", "-", "1",
                   "4+", "Rapid Fire (1), Sidearm", "C", "10"]),
            rows,
        )
        self.assertEqual(table_guard.data_drift(before, after), [])
        _passes_tables_gate(self, after)

    def test_idempotent(self):
        once = promote_header_below_separator(self._demoted())
        self.assertEqual(once, promote_header_below_separator(once))

    def test_passes_tables_gate(self):
        _passes_tables_gate(self, promote_header_below_separator(self._demoted()))

    def test_already_correct_header_untouched(self):
        text = _ttable(
            [
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits"],
                ["---"] * 10,
                ["Autogun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Rapid Fire (1)"],
            ]
        )
        self.assertEqual(promote_header_below_separator(text), text)

    def test_grenade_label_promoted(self):
        # The item-type label is "Grenade", not "Weapon"; the stat-label signature
        # (AP/D/Am/Traits) still identifies it as a demoted header.
        text = _ttable(
            [
                ["", "Range", "Range", "Accuracy", "Accuracy", "", "", "", "", "", "Credit"],
                ["---"] * 11,
                ["Grenade", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits", "Cost"],
                ["Frag grenade", "-", "Sx3", "-", "-", "3", "-", "1", "4+", "Blast (3\")", "30"],
            ]
        )
        out = promote_header_below_separator(text)
        rows = _table_lines(out)
        self.assertEqual(
            rows[0],
            _trow(["Grenade", "Range (S)", "Range (L)", "Accuracy (S)", "Accuracy (L)",
                   "S", "AP", "D", "Am", "Traits", "Credit (Cost)"]),
        )
        self.assertEqual(table_guard.data_drift(text, out), [])

    def test_titlecase_ap_label_promoted(self):
        # Real PDFs (e.g. House of Faith, House of Chains, core rulebook) render
        # this column "Ap" (title case), not the all-caps "AP" used elsewhere in
        # this test class -- the label match must be case-insensitive.
        text = _ttable(
            [
                ["", "Rng", "Rng", "Acc", "Acc", "", "", "", "", ""],
                ["---"] * 10,
                ["Weapon", "S", "L", "S", "L", "Str", "Ap", "D", "Am", "Traits"],
                ["Autogun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Rapid Fire (1)"],
            ]
        )
        out = promote_header_below_separator(text)
        rows = _table_lines(out)
        self.assertEqual(
            rows[0],
            _trow(["Weapon", "Rng (S)", "Rng (L)", "Acc (S)", "Acc (L)",
                   "Str", "Ap", "D", "Am", "Traits"]),
        )
        self.assertEqual(table_guard.data_drift(text, out), [])

    def test_bold_markdown_labels_promoted(self):
        # Some PDFs (e.g. House of Chains) render the demoted label row in bold
        # markdown (**Ap**, **D**, ...) -- the label match must strip "**" before
        # comparing, and the original bold markers must survive into the merged
        # header verbatim (no fabrication, just relocation).
        text = _ttable(
            [
                ["", "**Rng**", "**Rng**", "**Acc**", "**Acc**", "", "", "", "", ""],
                ["---"] * 10,
                ["**Weapon**", "**S**", "**L**", "**S**", "**L**", "**Str **",
                 "**Ap**", "**D**", "**Am**", "**Traits**"],
                ["Autogun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Rapid Fire (1)"],
            ]
        )
        out = promote_header_below_separator(text)
        rows = _table_lines(out)
        self.assertEqual(
            rows[0],
            _trow(["**Weapon**", "**Rng** (**S**)", "**Rng** (**L**)",
                   "**Acc** (**S**)", "**Acc** (**L**)", "**Str **",
                   "**Ap**", "**D**", "**Am**", "**Traits**"]),
        )
        self.assertEqual(table_guard.data_drift(text, out), [])

    def test_real_data_first_row_untouched(self):
        # First row after the separator is genuine data (no stat-label header
        # words) -> not the demoted shape, leave it alone.
        text = _ttable(
            [
                ["", "Rng", "Rng", "Acc", "Acc", "", "", "", "", ""],
                ["---"] * 10,
                ["Autogun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Rapid Fire (1)"],
                ["Lasgun", '18"', '24"', "+1", "-", "3", "-", "1", "2+", "Plentiful"],
            ]
        )
        self.assertEqual(promote_header_below_separator(text), text)

    def test_nonempty_group_first_cell_untouched(self):
        # Group row's first cell is not empty -> header is probably already real.
        text = _ttable(
            [
                ["X", "Rng", "Rng", "Acc", "Acc", "", "", "", "", ""],
                ["---"] * 10,
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits"],
                ["Autogun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Rapid Fire (1)"],
            ]
        )
        self.assertEqual(promote_header_below_separator(text), text)

    def test_small_table_untouched(self):
        text = _ttable(
            [
                ["", "A", "B"],
                ["---", "---", "---"],
                ["Weapon", "1", "2"],
                ["x", "3", "4"],
            ]
        )
        self.assertEqual(promote_header_below_separator(text), text)

    def test_guard_still_flags_real_data_drop_in_demoted_table(self):
        # The label-row exemption must NOT mask a genuine data-row change.
        before = self._demoted()
        # Drop a token from a real weapon data row.
        after = before.replace("|4+|Rapid Fire (1)|", "|4+||")
        drift = table_guard.data_drift(before, after)
        self.assertTrue(drift)
        self.assertIn("Rapid", " ".join(drift))


class TestCollapseTableHeaders(unittest.TestCase):
    def _two_row_header(self):
        return _ttable(
            [
                ["", "Range", "Range", "Accuracy", "Accuracy", "", "", "", "", "", "", "Credit"],
                ["Weapon", "S", "L", "S", "L", "S", "AP", "D", "Am", "Traits", "AL", "Cost"],
                ["---"] * 12,
                ["Autogun", '8"', '24"', "+1", "-", "3", "-", "1", "4+", "Rapid Fire (1)", "C", "15"],
            ]
        )

    def test_group_header_merged(self):
        out = collapse_table_headers(self._two_row_header())
        rows = _table_lines(out)
        self.assertEqual(len(rows), 3)  # group row folded into the header
        self.assertEqual(
            rows[0],
            _trow(["Weapon", "Range (S)", "Range (L)", "Accuracy (S)", "Accuracy (L)",
                   "S", "AP", "D", "Am", "Traits", "AL", "Credit (Cost)"]),
        )

    def test_data_row_untouched_and_guard_clean(self):
        before = self._two_row_header()
        after = collapse_table_headers(before)
        self.assertNotEqual(before, after)
        self.assertEqual(table_guard.data_drift(before, after), [])

    def test_idempotent(self):
        once = collapse_table_headers(self._two_row_header())
        self.assertEqual(once, collapse_table_headers(once))

    def test_passes_tables_gate(self):
        _passes_tables_gate(self, collapse_table_headers(self._two_row_header()))

    def test_misaligned_group_row_dropped(self):
        # Group row has a different column count -> cannot label-merge -> dropped.
        text = _ttable(
            [
                ["", "Range", "Range", "Accuracy"],  # 4 cols (misaligned)
                ["Weapon", "S", "L", "S", "L", "Str"],  # 6 cols
                ["---"] * 6,
                ["Gun", '8"', '24"', "+1", "-", "3"],
            ]
        )
        out = collapse_table_headers(text)
        rows = _table_lines(out)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], _trow(["Weapon", "S", "L", "S", "L", "Str"]))

    def test_ordinary_table_untouched(self):
        # Separator at index 1 -> single-row header -> nothing to collapse.
        text = _ttable(
            [
                ["Weapon", "S", "L", "S", "L", "Str"],
                ["---"] * 6,
                ["Gun", '8"', '24"', "+1", "-", "3"],
            ]
        )
        self.assertEqual(collapse_table_headers(text), text)

    def test_small_table_untouched(self):
        text = _ttable([["A", "B"], ["A", "B"], ["---", "---"], ["1", "2"]])
        self.assertEqual(collapse_table_headers(text), text)


class TestPromoteDemotedLabelRow(unittest.TestCase):
    """Benefit tables (2-5 cols): ``|Selections||| / sep / |Available|...|Cost|``."""

    def _house_patronage(self):
        return _ttable(
            [
                ["Selections", "", ""],
                ["---", "---", "---"],
                ["Available", "House Patronage Benefit", "Cost"],
                ["0-5", "The Underdog may randomly generate an additional gang tactic.", "100 credits each"],
                ["Unlimited", "The Underdog may temporarily hire a Brute or Hanger-on.", "Varies"],
            ]
        )

    def test_label_row_promoted_and_title_emitted(self):
        out = promote_demoted_label_row(self._house_patronage())
        self.assertIn("**Selections**", out)
        rows = _table_lines(out)
        self.assertEqual(rows[0], _trow(["Available", "House Patronage Benefit", "Cost"]))
        self.assertTrue(rows[1].startswith("|---"))
        self.assertIn(
            _trow(["0-5", "The Underdog may randomly generate an additional gang tactic.", "100 credits each"]),
            rows,
        )

    def test_guard_clean(self):
        before = self._house_patronage()
        after = promote_demoted_label_row(before)
        self.assertNotEqual(before, after)
        self.assertEqual(table_guard.data_drift(before, after), [])
        self.assertEqual(table_guard.data_drift_strict(before, after), [])

    def test_idempotent(self):
        once = promote_demoted_label_row(self._house_patronage())
        self.assertEqual(once, promote_demoted_label_row(once))

    def test_passes_tables_gate(self):
        _passes_tables_gate(self, promote_demoted_label_row(self._house_patronage()))

    def test_weapon_chart_untouched(self):
        text = TestPromoteHeaderBelowSeparator()._demoted()
        self.assertEqual(promote_demoted_label_row(text), text)

    def test_already_correct_header_untouched(self):
        text = _ttable(
            [
                ["Available", "House Patronage Benefit", "Cost"],
                ["---", "---", "---"],
                ["0-5", "Some benefit.", "100 credits each"],
            ]
        )
        self.assertEqual(promote_demoted_label_row(text), text)


class TestSplitAmTraits(unittest.TestCase):
    def _fused(self):
        return _ttable(
            [
                ["Weapon", "S", "L", "Str", "AP", "D", "Am Traits", "AL", "Cost"],
                ["---"] * 9,
                ["Autogun", '8"', '24"', "3", "-", "1", "4+ Rapid Fire (1)", "C", "15"],
                ["Knife", "-", "-", "3", "-", "1", "Melee, Parry", "M", "10"],
            ]
        )

    def test_column_split(self):
        out = split_am_traits(self._fused())
        rows = _table_lines(out)
        self.assertEqual(
            rows[0],
            _trow(["Weapon", "S", "L", "Str", "AP", "D", "Am", "Traits", "AL", "Cost"]),
        )
        self.assertIn(
            _trow(["Autogun", '8"', '24"', "3", "-", "1", "4+", "Rapid Fire (1)", "C", "15"]),
            rows,
        )

    def test_no_leading_token_gives_empty_am(self):
        out = split_am_traits(self._fused())
        self.assertIn(
            _trow(["Knife", "-", "-", "3", "-", "1", "", "Melee, Parry", "M", "10"]),
            _table_lines(out),
        )

    def test_uniform_column_count(self):
        out = split_am_traits(self._fused())
        widths = {len(r.split("|")) for r in _table_lines(out)}
        self.assertEqual(len(widths), 1)

    def test_passes_tables_gate(self):
        _passes_tables_gate(self, split_am_traits(self._fused()))

    def test_guard_clean(self):
        before = self._fused()
        after = split_am_traits(before)
        self.assertNotEqual(before, after)
        self.assertEqual(table_guard.data_drift(before, after), [])

    def test_idempotent(self):
        once = split_am_traits(self._fused())
        self.assertEqual(once, split_am_traits(once))

    def test_no_fused_column_untouched(self):
        text = _ttable(
            [
                ["Weapon", "S", "L", "Str", "AP", "D", "Am", "Traits"],
                ["---"] * 8,
                ["Gun", '8"', '24"', "3", "-", "1", "4+", "Rapid Fire (1)"],
            ]
        )
        self.assertEqual(split_am_traits(text), text)


class TestMergeWrappedNameRows(unittest.TestCase):
    def _name_wrap(self, orphan="grenades"):
        return _ttable(
            [
                ["Weapon", "S", "L", "S", "L", "Str", "Ap", "D", "Am", "Traits"],
                ["---"] * 10,
                ["- photon flash", '6"', '24"', "-1", "-", "2", "-", "1", "6+", "Blast, Flash"],
                [orphan] + [""] * 9,
            ]
        )

    def test_name_continuation_merged(self):
        out = merge_wrapped_name_rows(self._name_wrap())
        rows = _table_lines(out)
        self.assertEqual(len(rows), 3)  # orphan folded in
        self.assertIn(
            _trow(["- photon flash grenades", '6"', '24"', "-1", "-", "2", "-", "1", "6+", "Blast, Flash"]),
            rows,
        )

    def test_guard_clean_and_idempotent(self):
        before = self._name_wrap()
        after = merge_wrapped_name_rows(before)
        self.assertNotEqual(before, after)
        self.assertEqual(table_guard.data_drift(before, after), [])
        self.assertEqual(after, merge_wrapped_name_rows(after))

    def test_passes_tables_gate(self):
        _passes_tables_gate(self, merge_wrapped_name_rows(self._name_wrap()))

    def test_combi_weapon_subheader_not_merged(self):
        self.assertEqual(
            merge_wrapped_name_rows(self._name_wrap(orphan="Autogun combi-weapon")),
            self._name_wrap(orphan="Autogun combi-weapon"),
        )

    def test_italic_subheader_not_merged(self):
        self.assertEqual(
            merge_wrapped_name_rows(self._name_wrap(orphan="_Primary Component_")),
            self._name_wrap(orphan="_Primary Component_"),
        )

    def test_all_caps_section_label_not_merged(self):
        self.assertEqual(
            merge_wrapped_name_rows(self._name_wrap(orphan="PISTOLS")),
            self._name_wrap(orphan="PISTOLS"),
        )

    def test_orphan_after_separator_without_prior_data_not_merged(self):
        # No complete data row precedes the orphan -> nothing to merge into.
        text = _ttable(
            [
                ["Weapon", "S", "L", "S", "L", "Str", "Ap", "D", "Am", "Traits"],
                ["---"] * 10,
                ["orphan name"] + [""] * 9,
            ]
        )
        self.assertEqual(merge_wrapped_name_rows(text), text)

    def test_small_table_untouched(self):
        text = _ttable([["Name", "X"], ["---", "---"], ["a", "1"], ["b", ""]])
        self.assertEqual(merge_wrapped_name_rows(text), text)


class TestNaming(unittest.TestCase):
    def setUp(self):
        self.sections = toc_tree.build_sections(SAMPLE_TOC, page_count=8)
        self.paths = naming.compute_paths(self.sections, "sample-handbook")

    def test_leaf_path(self):
        self.assertEqual(
            self.paths["01.01"]["note_path"],
            "sample-handbook/01-introduction/01.01-background.md",
        )

    def test_branch_is_folder_note(self):
        self.assertEqual(
            self.paths["01"]["note_path"],
            "sample-handbook/01-introduction/01-introduction.md",
        )

    def test_link_target_has_no_extension(self):
        self.assertEqual(
            self.paths["02.01"]["link_target"],
            "sample-handbook/02-methods/02.01-data-collection",
        )

    def test_uniform_layout_makes_leaves_folders(self):
        # In uniform layout every section (leaf included) is a folder note, so
        # Obsidian's folders-before-files explorer keeps ToC order.
        uni = naming.compute_paths(self.sections, "sample-handbook", layout="uniform")
        self.assertEqual(
            uni["01.01"]["note_path"],
            "sample-handbook/01-introduction/01.01-background/01.01-background.md",
        )
        # Branch sections are unchanged between layouts.
        self.assertEqual(
            uni["01"]["note_path"], self.paths["01"]["note_path"]
        )

    def test_source_moc_path(self):
        self.assertEqual(
            naming.source_moc_path("sample-handbook"),
            "sample-handbook/sample-handbook.md",
        )

    def test_relative_asset_ref_depth(self):
        # note one level below source -> one '../'
        self.assertEqual(
            naming.relative_asset_ref("s", "s/01-intro", "fig.png"),
            "../assets/fig.png",
        )
        # per-PDF MOC sits at source root -> no '../'
        self.assertEqual(
            naming.relative_asset_ref("s", "s", "fig.png"), "assets/fig.png"
        )

    def test_unique_paths(self):
        all_paths = [v["note_path"] for v in self.paths.values()]
        self.assertEqual(len(all_paths), len(set(all_paths)))

    def test_obsidian_index_none_when_standalone(self):
        # No .obsidian ancestor -> caller falls back to bare [[index]].
        with tempfile.TemporaryDirectory() as tmp:
            vault = os.path.join(tmp, "pdf-vault-output")
            os.makedirs(vault)
            self.assertIsNone(naming.obsidian_relative_index(vault))

    def test_obsidian_index_qualified_when_nested(self):
        # Vault inside an Obsidian vault -> Obsidian-root-relative index target.
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".obsidian"))
            vault = os.path.join(tmp, "Games", "Bolt Action", "Core rulebook", "3")
            os.makedirs(vault)
            self.assertEqual(
                naming.obsidian_relative_index(vault),
                "Games/Bolt Action/Core rulebook/3/index",
            )

    def test_obsidian_index_bare_when_vault_is_root(self):
        # The vault root *is* the Obsidian root -> bare 'index' (still unique).
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".obsidian"))
            self.assertEqual(naming.obsidian_relative_index(tmp), "index")


class TestFrontmatter(unittest.TestCase):
    def test_render_order_and_omit(self):
        meta = {
            "title": "1.1 Background",
            "source": "book.pdf",
            "source_pages": [1, 2],
            "boundary": "page-level",
            "toc_level": 2,
            "toc_number": "01.01",
            "tags": ["pdf-import", "book"],
            "created": "2026-06-27",
            "generated_by": "p2v",
        }
        out = frontmatter.render(meta)
        # 'parent'/'prev'/'next' omitted (absent), key order preserved
        self.assertIn('title: "1.1 Background"', out)
        self.assertIn("source_pages: [1, 2]", out)
        self.assertIn("tags: [pdf-import, book]", out)
        self.assertNotIn("parent:", out)
        self.assertLess(out.index("title:"), out.index("source:"))

    def test_round_trip(self):
        meta = {
            "title": "Has: colon and \"quote\"",
            "source": "book.pdf",
            "source_pages": [3, 9],
            "toc_level": 1,
            "toc_number": "02",
            "parent": "[[a/b/c|Display]]",
            "tags": ["pdf-import", "book"],
            "created": "2026-06-27",
            "generated_by": "p2v",
        }
        text = frontmatter.render_note(meta, "# Body\n\ncontent")
        parsed, body = frontmatter.split(text)
        self.assertEqual(parsed["title"], 'Has: colon and "quote"')
        self.assertEqual(parsed["parent"], "[[a/b/c|Display]]")
        self.assertEqual(parsed["source_pages"], [3, 9])
        self.assertTrue(body.startswith("# Body"))

    def test_split_no_frontmatter(self):
        meta, body = frontmatter.split("no frontmatter here")
        self.assertIsNone(meta)
        self.assertEqual(body, "no frontmatter here")

    def test_summary_rendered_after_tags_and_round_trips(self):
        meta = {
            "title": "1.1 Background",
            "source": "book.pdf",
            "source_pages": [1, 2],
            "toc_level": 2,
            "toc_number": "01.01",
            "tags": ["pdf-import", "book", "topic/melee", "enriched"],
            "summary": 'A faithful: one-line "condensation".',
            "created": "2026-06-27",
            "generated_by": "p2v",
        }
        out = frontmatter.render(meta)
        self.assertLess(out.index("tags:"), out.index("summary:"))
        self.assertLess(out.index("summary:"), out.index("created:"))
        parsed, _ = frontmatter.split(out + "\n\nbody")
        self.assertEqual(parsed["summary"], 'A faithful: one-line "condensation".')


class TestLinks(unittest.TestCase):
    def test_wikilink_and_extract(self):
        wl = links.wikilink("a/b/c", "Title")
        self.assertEqual(wl, "[[a/b/c|Title]]")
        self.assertEqual(links.extract_links(wl), [("a/b/c", "Title")])

    def test_extract_links_table_escaped_pipe(self):
        # Inside a markdown table the wikilink pipe is escaped as `\|` so it is
        # not read as a column separator. The target must still resolve cleanly
        # (no trailing backslash).
        cell = r"| Topic | [[book/24-force-selection/24.02-rifle-platoon\|24.2 Rifle Platoon]] |"
        self.assertEqual(
            links.extract_links(cell),
            [("book/24-force-selection/24.02-rifle-platoon", "24.2 Rifle Platoon")],
        )

    def test_is_bare(self):
        self.assertTrue(links.is_bare("background"))
        self.assertFalse(links.is_bare("book/01-intro/background"))

    def test_managed_block_sorted(self):
        block = links.render_managed_block([("b/b", "B"), ("a/a", "A")])
        self.assertLess(block.index("a/a"), block.index("b/b"))
        self.assertIn(links.AUTO_START, block)
        self.assertIn(links.AUTO_END, block)

    def test_upsert_preserves_surrounding(self):
        existing = "# Header\n\ntop notes\n\n" + links.render_managed_block(
            [("x/x", "X")]
        ) + "\n\nbottom notes\n"
        new_block = links.render_managed_block([("y/y", "Y")])
        updated = links.upsert_managed_region(existing, new_block)
        self.assertIn("top notes", updated)
        self.assertIn("bottom notes", updated)
        self.assertIn("y/y", updated)
        self.assertNotIn("x/x", updated)

    def test_upsert_appends_when_absent(self):
        updated = links.upsert_managed_region(
            "# Header\n\nbody\n", links.render_managed_block([("z/z", "Z")])
        )
        self.assertIn("# Header", updated)
        self.assertIn(links.AUTO_START, updated)
        # a blank line must separate prior content from the block
        self.assertIn("body\n\n<!-- p2v:auto-start -->", updated)


class TestLibraryIndexDedup(unittest.TestCase):
    """A stale entry for a source under an older link convention (bare
    `[[slug]]`) must be replaced, not duplicated, on rebuild."""

    def test_dedupes_by_source_slug(self):
        slug = "frostgrave-second-edition"
        with tempfile.TemporaryDirectory() as tmp:
            # Pre-seed index.md with a stale bare entry for this source.
            stale_block = links.render_managed_block([(slug, "Frostgrave (old)")])
            existing = "# Imported PDFs\n\n" + stale_block + "\n"
            with open(os.path.join(tmp, naming.LIBRARY_INDEX), "w", encoding="utf-8") as fh:
                fh.write(existing)

            build_vault._update_library_index(tmp, slug, "Frostgrave: Second Edition")

            with open(os.path.join(tmp, naming.LIBRARY_INDEX), encoding="utf-8") as fh:
                out = fh.read()
            targets = [t for (t, _a) in links.extract_links(out)]
            # Exactly one entry, and it is the qualified MOC target.
            self.assertEqual(targets, [f"{slug}/{slug}"])
            self.assertNotIn(f"[[{slug}|", out)  # bare form gone

    def test_preserves_other_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = ("bolt-action-third-edition/bolt-action-third-edition", "Bolt Action")
            seed = links.render_managed_block([other])
            with open(os.path.join(tmp, naming.LIBRARY_INDEX), "w", encoding="utf-8") as fh:
                fh.write("# Imported PDFs\n\n" + seed + "\n")

            build_vault._update_library_index(tmp, "frostgrave-second-edition", "Frostgrave")

            with open(os.path.join(tmp, naming.LIBRARY_INDEX), encoding="utf-8") as fh:
                targets = [t for (t, _a) in links.extract_links(fh.read())]
            self.assertIn(other[0], targets)
            self.assertIn("frostgrave-second-edition/frostgrave-second-edition", targets)


class TestBranchPreambleRender(unittest.TestCase):
    """Branch folder notes render preamble body (when present) above their
    Contents list, and stay byte-identical to the old Contents-only form when a
    manifest carries no branch markdown (backward-compatibility guarantee)."""

    # A chapter (01) with a preamble before its single bookmarked child (01.01).
    _TOC = [[1, "Gang List", 34], [2, "Exotic Beasts", 49], [1, "Next", 51]]

    def _manifest(self, sections, slug="bk"):
        return {
            "source": {
                "source_slug": slug,
                "title": "Book",
                "file_name": "book.pdf",
                "extracted_at": "2026-06-27",
                "page_count": 60,
                "assets_staging_dir": None,
            },
            "sections": sections,
        }

    def _branch_note(self, tmp, slug="bk"):
        path = os.path.join(tmp, slug, "01-gang-list", "01-gang-list.md")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_branch_without_markdown_is_contents_only(self):
        # The pre-fix manifest shape (build_sections sets no 'markdown') must
        # render exactly as before: title + Contents, no preamble section.
        sections = toc_tree.build_sections(self._TOC, page_count=60)
        with tempfile.TemporaryDirectory() as tmp:
            build_vault.build(
                self._manifest(sections), tmp, set(),
                layout="nested", index_link_mode="root",
            )
            _meta, body = frontmatter.split(self._branch_note(tmp))
            self.assertEqual(
                body.strip(),
                "# 1 Gang List\n\n## Contents\n\n"
                "- [[bk/01-gang-list/01.01-exotic-beasts|1.1 Exotic Beasts]]",
            )

    def test_branch_with_markdown_renders_preamble_above_contents(self):
        sections = toc_tree.build_sections(self._TOC, page_count=60)
        for s in sections:
            if s["toc_number"] == "01":
                s["markdown"] = "UNIQUE_PREAMBLE_MARKER body text."
                s["assets"] = []
        with tempfile.TemporaryDirectory() as tmp:
            build_vault.build(
                self._manifest(sections), tmp, set(),
                layout="nested", index_link_mode="root",
            )
            body = self._branch_note(tmp)
            self.assertIn("UNIQUE_PREAMBLE_MARKER", body)
            self.assertIn("## Contents", body)
            # preamble sits above the Contents list, under the title H1.
            self.assertLess(
                body.index("UNIQUE_PREAMBLE_MARKER"), body.index("## Contents")
            )


class TestVerifyGates(unittest.TestCase):
    """The tightened `tables` gate flags only column-count inconsistency, and the
    `boilerplate` gate is a no-op until configured. Locks the false-positive fix."""

    def _write(self, tmp, name, body):
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return name

    def test_tables_flags_ragged_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._write(tmp, "r.md", "|A|B|C|\n|---|---|---|\n|1|2|3|\n|x|y|\n")
            fails: list = []
            verify_vault.check_tables(tmp, [rel], fails)
            self.assertTrue(any("inconsistent table column counts" in f for f in fails))

    def test_tables_ignores_single_cell_subtotal(self):
        # The Bolt Action subtotal shape: consistent width, not flagged.
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._write(tmp, "s.md", "|Sniper|Reg|2||52|\n|||||504|")
            fails: list = []
            verify_vault.check_tables(tmp, [rel], fails)
            self.assertEqual(fails, [])

    def test_tables_ignores_all_empty_form_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._write(tmp, "f.md", "|A|B|\n|---|---|\n|1|2|\n|||")
            fails: list = []
            verify_vault.check_tables(tmp, [rel], fails)
            self.assertEqual(fails, [])

    def test_boilerplate_noop_when_unconfigured(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._write(tmp, "b.md", "**This ebook belongs to Tim**")
            fails: list = []
            verify_vault.check_boilerplate(tmp, [rel], fails, [])
            self.assertEqual(fails, [])

    def test_boilerplate_flags_configured_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._write(tmp, "b.md", "body\n\n**This ebook belongs to Tim**\n")
            fails: list = []
            verify_vault.check_boilerplate(tmp, [rel], fails, [_DRM])
            self.assertEqual(len(fails), 1)
            self.assertIn("[boilerplate]", fails[0])

    def test_heading_artifacts_flags_spaced_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._write(tmp, "h.md", "## C H A P T E R  F O U R SPELLS\n\nBody.\n")
            fails: list = []
            verify_vault.check_heading_artifacts(tmp, [rel], fails)
            self.assertEqual(len(fails), 1)
            self.assertIn("[heading_artifacts]", fails[0])

    def test_heading_artifacts_ignores_clean_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._write(tmp, "h.md", "## Chapter Four: Spells\n\nBody.\n")
            fails: list = []
            verify_vault.check_heading_artifacts(tmp, [rel], fails)
            self.assertEqual(fails, [])

    def test_heading_artifacts_ignores_stat_table_body(self):
        # A stat line is NOT a heading -> never flagged (mirrors the fix scope).
        with tempfile.TemporaryDirectory() as tmp:
            rel = self._write(tmp, "s.md", "M WS BS S T W I A Ld Cl Wil Int\n")
            fails: list = []
            verify_vault.check_heading_artifacts(tmp, [rel], fails)
            self.assertEqual(fails, [])


def _frag(text, x0, y, size=10.0, bold=False):
    return {"text": text, "x0": x0, "x1": x0 + max(1, len(text)) * 5.0, "y": y, "size": size, "bold": bold}


class TestIndexLayout(unittest.TestCase):
    """Geometry-driven index reconstruction (lib.index_layout)."""

    def _two_col_page(self):
        # Column 0 at x0~10 (A entries), column 1 at x0~200 (B entries); a wide
        # gutter between ~60 and ~200. Letter heads are larger; a giant "INDEX"
        # title and a footer page number sit outside the entry size / columns.
        return [
            _frag("INDEX", 10, 0, size=30.0),
            _frag("A", 10, 10, size=16.0),
            _frag("Advance 69", 10, 20),
            _frag("Action phase................99", 10, 30),
            _frag("B", 200, 10, size=16.0),
            _frag("Banzai 80", 200, 20),
            _frag("318", 2, 400, size=8.0),  # footer page number, left of column 0
        ]

    def test_orders_by_column_then_strips_furniture(self):
        md = reconstruct_index([self._two_col_page()], title="36 Index")
        lines = md.splitlines()
        self.assertEqual(lines[0], "## INDEX")
        # Column-major A-Z order: all of column 0 (A) before column 1 (B).
        self.assertEqual(
            [l for l in lines if l.startswith(("### ", "- "))],
            ["### A", "- Advance 69", "- Action phase 99", "### B", "- Banzai 80"],
        )
        # The giant title and the footer number are dropped, not emitted as entries.
        self.assertNotIn("- INDEX", md)
        self.assertNotIn("- 318", md)

    def test_dotted_leaders_collapsed(self):
        md = reconstruct_index([self._two_col_page()], title="36 Index")
        self.assertIn("- Action phase 99", md)
        self.assertNotIn("....", md)

    def test_single_column_returns_none(self):
        # No multi-column structure -> caller falls back to normal extraction.
        page = [_frag("Advance 69", 10, 20), _frag("Ambush 70", 10, 30)]
        self.assertIsNone(reconstruct_index([page], title="Index"))


class TestIndexLinkify(unittest.TestCase):
    """build_vault page-number -> wikilink resolution for index notes."""

    def _fixture(self):
        sections = [
            {"toc_number": "01", "title": "Movement", "is_leaf": True,
             "start_page": 74, "end_page": 77, "markdown": "## MOVEMENT\n\nbody"},
            {"toc_number": "02", "title": "Index", "is_leaf": True, "kind": "index",
             "start_page": 80, "end_page": 81, "markdown": "## INDEX"},
        ]
        paths = {
            "01": {"link_target": "book/01-movement"},
            "02": {"link_target": "book/02-index"},
        }
        return sections, paths

    def test_page_targets_leaf_coverage(self):
        sections, paths = self._fixture()
        pt = build_vault._page_targets(sections, paths)
        self.assertEqual(pt[74], "book/01-movement")
        self.assertEqual(pt[77], "book/01-movement")
        self.assertEqual(pt[80], "book/02-index")
        self.assertNotIn(999, pt)

    def test_linkify_adds_anchor_on_heading_match(self):
        sections, paths = self._fixture()
        pt = build_vault._page_targets(sections, paths)
        hd = build_vault._headings_by_target(sections, paths)
        body = "## INDEX\n\n### M\n\n- Movement 74\n- Crossing 75, 999"
        out = build_vault._linkify_index_body(body, pt, hd)
        # term "Movement" matches the heading in the page-74 note -> anchored link
        self.assertIn("- Movement [[book/01-movement#MOVEMENT|74]]", out)
        # "Crossing" has no matching heading -> plain note link; 999 has no note.
        self.assertIn("- Crossing [[book/01-movement|75]], 999", out)

    def test_linkify_preserves_bold_main_reference(self):
        sections, paths = self._fixture()
        pt = build_vault._page_targets(sections, paths)
        hd = build_vault._headings_by_target(sections, paths)
        out = build_vault._linkify_index_body("- Foo **80**", pt, hd)
        self.assertIn("- Foo **[[book/02-index|80]]**", out)

    def test_linkify_ignores_non_entry_lines(self):
        sections, paths = self._fixture()
        pt = build_vault._page_targets(sections, paths)
        hd = build_vault._headings_by_target(sections, paths)
        for line in ("## INDEX", "### A", "- attacking vehicles"):
            self.assertEqual(build_vault._linkify_index_body(line, pt, hd), line)


class TestTocFromHeadings(unittest.TestCase):
    def test_normal_multi_page(self):
        pages = [
            "## Introduction\n\nbody text",
            "## Methods\n\nmore body",
            "## Results\n\nfinal body",
        ]
        self.assertEqual(
            toc_from_headings(pages),
            [[1, "Introduction", 1], [1, "Methods", 2], [1, "Results", 3]],
        )

    def test_levels_flattened_to_one(self):
        # A `#` title and a `##` section-header both become level 1 (flat).
        pages = ["# Big Title\n\nbody", "### Deep Heading\n\nbody"]
        self.assertEqual(
            toc_from_headings(pages),
            [[1, "Big Title", 1], [1, "Deep Heading", 2]],
        )

    def test_same_page_collapses_to_first(self):
        pages = ["## First Heading\n\ntext\n\n## Second Heading\n\nmore"]
        self.assertEqual(toc_from_headings(pages), [[1, "First Heading", 1]])

    def test_leading_gap_filled_single_page(self):
        # First heading on page 2 -> a "Page 1" entry captures the page before it.
        pages = ["plain body, no heading", "## Real Start\n\nbody"]
        self.assertEqual(
            toc_from_headings(pages),
            [[1, "Page 1", 1], [1, "Real Start", 2]],
        )

    def test_leading_gap_filled_multi_page(self):
        pages = ["body a", "body b", "## Real Start\n\nbody"]
        self.assertEqual(
            toc_from_headings(pages),
            [[1, "Pages 1-2", 1], [1, "Real Start", 3]],
        )

    def test_heading_in_code_fence_ignored(self):
        pages = [
            "```\n## not a heading\n```\n\n## Real Heading\n\nbody",
        ]
        self.assertEqual(toc_from_headings(pages), [[1, "Real Heading", 1]])

    def test_emphasis_markers_stripped(self):
        pages = ["## **Bold Title** `code`\n\nbody"]
        self.assertEqual(toc_from_headings(pages), [[1, "Bold Title code", 1]])

    def test_emphasis_only_heading_skipped(self):
        # A heading whose text is nothing but emphasis markers is not usable;
        # the next real heading (on a later page) wins.
        pages = ["## **__**\n\nbody", "## Real\n\nbody"]
        self.assertEqual(
            toc_from_headings(pages),
            [[1, "Page 1", 1], [1, "Real", 2]],
        )

    def test_no_headings_returns_empty(self):
        pages = ["just prose", "more prose", "```\n# fenced\n```"]
        self.assertEqual(toc_from_headings(pages), [])

    def test_empty_input_returns_empty(self):
        self.assertEqual(toc_from_headings([]), [])


def _toc_frag(text: str, x0: float, y: float = 10.0) -> dict:
    """Helper: minimal fragment dict for toc_page tests."""
    return {"text": text, "x0": x0, "x1": x0 + len(text) * 6.0, "y": y, "size": 10.0, "bold": False}


class TestTocPage(unittest.TestCase):
    """Tests for lib.toc_page: row assembly, level inference, leader stripping,
    offset detection, the no-structure path, and the degeneracy hint helper."""

    # ------------------------------------------------------------------
    # Dotted-leader stripping
    # ------------------------------------------------------------------

    def test_strip_leaders_basic(self):
        self.assertEqual(_strip_leaders("Introduction ........ 1"), "Introduction 1")

    def test_strip_leaders_middle_dot(self):
        self.assertEqual(_strip_leaders("Methods \u00b7\u00b7\u00b7\u00b7 4"), "Methods 4")

    def test_strip_leaders_ellipsis(self):
        self.assertEqual(_strip_leaders("Results \u2026\u2026 7"), "Results 7")

    def test_strip_leaders_no_leaders(self):
        self.assertEqual(_strip_leaders("Plain text 5"), "Plain text 5")

    # ------------------------------------------------------------------
    # Row parsing
    # ------------------------------------------------------------------

    def test_parse_rows_basic(self):
        frags = [
            _toc_frag("Introduction", 50, 10),
            _toc_frag("........", 150, 10),
            _toc_frag("1", 200, 10),
        ]
        rows = _parse_rows([[frags[0], frags[1], frags[2]]])
        self.assertEqual(len(rows), 1)
        title, page, x0 = rows[0]
        self.assertIn("Introduction", title)
        self.assertEqual(page, 1)

    def test_parse_rows_no_page_number(self):
        frags = [_toc_frag("Section Heading", 50, 10)]
        rows = _parse_rows([[frags[0]]])
        self.assertEqual(len(rows), 1)
        title, page, x0 = rows[0]
        self.assertEqual(page, None)

    # ------------------------------------------------------------------
    # Indentation band detection
    # ------------------------------------------------------------------

    def test_x0_bands_distinct(self):
        # 50 and 51 are within tol=2.5 → merge; 60 and 75 are separate → 3 bands
        bands = _x0_bands([50.0, 51.0, 60.0, 75.0])
        self.assertEqual(len(bands), 3)
        self.assertAlmostEqual(bands[0], 50.0)

    def test_x0_bands_single_level(self):
        bands = _x0_bands([53.0, 53.1, 52.9])
        self.assertEqual(len(bands), 1)

    # ------------------------------------------------------------------
    # Indentation-mode hierarchy
    # ------------------------------------------------------------------

    def _make_indent_page(self):
        """Mimic the annex PDF's ToC page layout."""
        y = 10.0
        frags = []
        entries = [
            (53.8, "Foundation Platform", "2"),
            (64.8, "Self-Serve Silver", "5"),
            (75.8, "Pack Detail Page", "7"),
            (83.8, "Project & Pack Store", "9"),
            (53.8, "Internal Platform", "12"),
        ]
        for x0, title, pg in entries:
            frags.append(_toc_frag(title, x0, y))
            frags.append(_toc_frag("......", x0 + 100, y))
            frags.append(_toc_frag(pg, x0 + 180, y))
            y += 12.0
        return [frags]

    def test_indent_hierarchy(self):
        pages_frags = self._make_indent_page()
        page_md = [""] * 20  # no heading match needed for this test (offset=0)
        toc, warnings = toc_from_toc_page(pages_frags, page_md, hierarchy_mode="indent")
        self.assertGreater(len(toc), 0, "Should produce a non-empty ToC")
        levels = [row[0] for row in toc]
        # Foundation Platform and Internal Platform are L1 (leftmost x0)
        self.assertEqual(levels[0], 1)
        # Self-Serve Silver is deeper
        self.assertGreater(levels[1], levels[0])
        # Pack Detail Page is deeper still
        self.assertGreater(levels[2], levels[1])

    # ------------------------------------------------------------------
    # Numbered-prefix hierarchy
    # ------------------------------------------------------------------

    def _make_numbered_page(self):
        y = 10.0
        frags = []
        entries = [
            (50, "1 Introduction", "1"),
            (50, "1.1 Background", "2"),
            (50, "1.2 Scope", "4"),
            (50, "2 Methods", "6"),
            (50, "2.1 Data Collection", "7"),
        ]
        for x0, title, pg in entries:
            frags.append(_toc_frag(title, x0, y))
            frags.append(_toc_frag("......", x0 + 150, y))
            frags.append(_toc_frag(pg, x0 + 200, y))
            y += 12.0
        return [frags]

    def test_numbered_hierarchy(self):
        pages_frags = self._make_numbered_page()
        page_md = [""] * 10
        toc, warnings = toc_from_toc_page(pages_frags, page_md, hierarchy_mode="numbered")
        self.assertEqual(len(toc), 5)
        levels = [row[0] for row in toc]
        titles = [row[1] for row in toc]
        self.assertEqual(levels, [1, 2, 2, 1, 2])
        self.assertIn("Introduction", titles[0])
        self.assertIn("Background", titles[1])

    def test_auto_picks_numbered_when_majority_have_prefix(self):
        pages_frags = self._make_numbered_page()
        page_md = [""] * 10
        toc, _ = toc_from_toc_page(pages_frags, page_md, hierarchy_mode="auto")
        levels = [row[0] for row in toc]
        # auto should match numbered
        self.assertEqual(levels, [1, 2, 2, 1, 2])

    def test_auto_picks_indent_when_no_prefixes(self):
        pages_frags = self._make_indent_page()
        page_md = [""] * 20
        toc, _ = toc_from_toc_page(pages_frags, page_md, hierarchy_mode="auto")
        levels = [row[0] for row in toc]
        self.assertEqual(levels[0], 1)  # L1 stays L1 under indent

    # ------------------------------------------------------------------
    # Page-offset detection
    # ------------------------------------------------------------------

    def test_offset_detection_with_matching_headings(self):
        # Printed page 1 = physical page 3 (offset=+2), printed 2 = physical 4.
        # Use 3 rows all with the same offset so the modal vote is unambiguous.
        rows = [
            ("Introduction", 1, 50.0),
            ("Background", 2, 50.0),
            ("Methods", 3, 50.0),
        ]
        page_md = [
            "",
            "",
            "# Introduction\n\nbody",
            "# Background\n\nbody",
            "# Methods\n\nbody",
        ]
        offset, warnings = detect_page_offset(rows, page_md)
        self.assertEqual(offset, 2)

    def test_offset_zero_when_no_match(self):
        rows = [("Unmatched Title", 5, 50.0)]
        page_md = ["# Something Else\n\nbody"] * 5
        offset, warnings = detect_page_offset(rows, page_md)
        self.assertEqual(offset, 0)
        self.assertGreater(len(warnings), 0)

    def test_offset_applied_in_toc_from_toc_page(self):
        # Build a simple numbered ToC where printed page 1 maps to physical 3.
        y = 10.0
        frags = []
        for title, pg in [("1 Intro", "1"), ("1.1 Background", "2")]:
            frags.append(_toc_frag(title, 50, y))
            frags.append(_toc_frag("......", 200, y))
            frags.append(_toc_frag(pg, 250, y))
            y += 12.0
        page_md = ["", "", "# Intro\n\nbody", "# Background\n\nbody"] + [""] * 5
        toc, _ = toc_from_toc_page([frags], page_md, hierarchy_mode="numbered")
        # Physical pages should be shifted by +2
        self.assertEqual(toc[0][2], 3)  # printed 1 + offset 2 = 3
        self.assertEqual(toc[1][2], 4)  # printed 2 + offset 2 = 4

    # ------------------------------------------------------------------
    # No-structure path
    # ------------------------------------------------------------------

    def test_empty_frags_returns_empty_toc(self):
        toc, warnings = toc_from_toc_page([[]], [], hierarchy_mode="auto")
        self.assertEqual(toc, [])
        self.assertGreater(len(warnings), 0)

    def test_no_page_numbers_returns_empty_toc(self):
        frags = [_toc_frag("Just a heading without a page number", 50, 10)]
        toc, warnings = toc_from_toc_page([[frags[0]]], [], hierarchy_mode="auto")
        self.assertEqual(toc, [])
        self.assertGreater(len(warnings), 0)

    # ------------------------------------------------------------------
    # embedded_toc_looks_degenerate
    # ------------------------------------------------------------------

    def test_degenerate_bare_page_numbers(self):
        # Annex pattern: all titles are page numbers.
        raw_toc = [[1, "3", 3], [1, "4", 4], [1, "5", 5], [1, "6", 6]]
        self.assertTrue(embedded_toc_looks_degenerate(raw_toc))

    def test_degenerate_all_level1_numeric_titles(self):
        raw_toc = [[1, "10", 10], [1, "20", 20], [1, "30", 30]]
        self.assertTrue(embedded_toc_looks_degenerate(raw_toc))

    def test_not_degenerate_normal_toc(self):
        raw_toc = [
            [1, "Introduction", 1],
            [2, "Background", 2],
            [2, "Scope", 4],
            [1, "Methods", 6],
        ]
        self.assertFalse(embedded_toc_looks_degenerate(raw_toc))

    def test_not_degenerate_mixed_some_numeric_titles(self):
        # Only 1 out of 4 is numeric → not degenerate.
        raw_toc = [
            [1, "Introduction", 1],
            [2, "Chapter 2", 3],
            [1, "5", 5],
            [1, "Conclusion", 9],
        ]
        self.assertFalse(embedded_toc_looks_degenerate(raw_toc))

    def test_degenerate_empty_toc(self):
        self.assertFalse(embedded_toc_looks_degenerate([]))


if __name__ == "__main__":
    unittest.main()
