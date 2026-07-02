#!/usr/bin/env python3
"""Stage 2: manifest.json -> Obsidian vault (notes, MOCs, assets, library index).

Reads only the manifest (never the PDF). Honors the safe-write model: it only
overwrites files it owns (frontmatter ``generated_by: p2v`` + listed in the
generated set), and only edits the managed region of the library index.

Usage:
    python build_vault.py ../.p2v/<slug>.manifest.json --vault <vault-output>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import frontmatter, links, naming, toc_tree  # noqa: E402
from lib.text import clean_inline, clean_block  # noqa: E402

_ASSET_SENTINEL = re.compile(r"!\[\]\(ASSET:([^)]+)\)")
GENERATED_BY = "p2v"

# An index entry list item: "- <term>  <page-number group>".
_INDEX_ENTRY = re.compile(r"^(- )(.*?)(\s+)(\*{0,2}\d[\d,\u2013\-\s*]*)$")
# A leading enumerator on a heading ("1. ", "2) ") to drop before matching.
_ENUMERATOR = re.compile(r"^\s*\d+[.)]\s*")
_HEADING = re.compile(r"^#{1,6}\s+(.*\S)\s*$")


def _norm(text: str) -> str:
    """Loose key for matching an index term to a heading (case/punct-insensitive)."""
    text = re.sub(r"[*_`#]", "", text)
    text = _ENUMERATOR.sub("", text)
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _page_targets(sections: list, paths: dict) -> dict:
    """Map each source page -> the wikilink target of the note that covers it.

    Leaves win over branches (a branch spans all its children's pages, so it is
    only used to fill pages no leaf claims, e.g. chapter preamble).
    """
    out: dict = {}
    for leaf_first in (True, False):
        for s in sections:
            if s["is_leaf"] != leaf_first:
                continue
            tgt = paths[s["toc_number"]]["link_target"]
            for p in range(s["start_page"], s["end_page"] + 1):
                out.setdefault(p, tgt)
    return out


def _headings_by_target(sections: list, paths: dict) -> dict:
    """Map note target -> {normalized-heading: display-heading} for anchoring."""
    out: dict = {}
    for s in sections:
        tgt = paths[s["toc_number"]]["link_target"]
        heads: dict = {}
        for line in (s.get("markdown") or "").split("\n"):
            m = _HEADING.match(line)
            if not m:
                continue
            disp = _ENUMERATOR.sub("", re.sub(r"\*\*|__|`", "", m.group(1))).strip()
            key = _norm(disp)
            if key:
                heads.setdefault(key, disp)
        out[tgt] = heads
    return out


def _linkify_index_body(body: str, page_targets: dict, headings_for: dict) -> str:
    """Turn the plain page numbers in a reconstructed index into wikilinks.

    Each entry's trailing page-number group is split into atomic references;
    every reference links to the note covering that page (a range/comma list
    links its first page), aliased by the printed number. When the entry term
    matches a heading in the target note, the link carries that heading anchor.
    Bold (main-reference) numbers keep their emphasis. Numbers with no covering
    note are left as plain text.
    """
    out = []
    for line in body.split("\n"):
        m = _INDEX_ENTRY.match(line)
        if not m:
            out.append(line)
            continue
        bullet, term, gap, pages = m.groups()
        term_key = _norm(term)
        rendered = []
        for piece in pages.split(","):
            piece = piece.strip()
            if not piece:
                continue
            bold = piece.startswith("**")
            core = piece.strip("*").strip()
            num = re.match(r"(\d+)", core)
            tgt = page_targets.get(int(num.group(1))) if num else None
            if not tgt:
                rendered.append(piece)
                continue
            anchor = ""
            disp = headings_for.get(tgt, {}).get(term_key)
            if disp:
                anchor = "#" + disp
            link = links.wikilink(tgt + anchor, core)
            rendered.append(f"**{link}**" if bold else link)
        out.append(f"{bullet}{term}{gap}" + ", ".join(rendered))
    return "\n".join(out)


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _safe_write(vault: str, rel_path: str, content: str, owned: set, prior: set) -> None:
    """Write a fully-owned file, refusing to clobber user-authored notes.

    A path is ours if it was recorded as generated on a previous run (`prior`)
    or its frontmatter carries `generated_by: p2v`. The `prior` check also lets
    us reclaim files whose frontmatter got corrupted (e.g. by bad source text).
    """
    abs_path = os.path.join(vault, rel_path)
    if os.path.exists(abs_path) and rel_path not in prior:
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            existing = fh.read()
        meta, _ = frontmatter.split(existing)
        if not (meta and meta.get("generated_by") == GENERATED_BY):
            raise SystemExit(
                f"Refusing to overwrite user-authored file: {rel_path}\n"
                "It lacks 'generated_by: p2v'. Move or delete it, then re-run."
            )
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    owned.add(rel_path)


def _parent_link(node, by_number, paths, source_slug, title):
    pnum = node.get("parent_number")
    if pnum is None:
        return links.wikilink(f"{source_slug}/{source_slug}", title)
    parent = by_number[pnum]
    return links.wikilink(paths[pnum]["link_target"], parent["display_title"])


def _resolve_assets(body: str, source_slug: str, note_dir: str) -> str:
    def repl(m):
        rel = naming.relative_asset_ref(source_slug, note_dir, m.group(1))
        return f"![]({rel})"

    return _ASSET_SENTINEL.sub(repl, body)


def _library_index_target(vault: str, mode: str) -> str:
    """Wikilink target the per-PDF MOC uses for its `parent` (the library index).

    ``mode == "root"`` forces the bare ``index`` link. ``"auto"`` (default)
    qualifies it with the Obsidian-root-relative path when the vault sits inside
    a larger Obsidian vault, so multiple libraries don't collide on ``[[index]]``.
    """
    if mode == "root":
        return "index"
    return naming.obsidian_relative_index(vault) or "index"


def build(
    manifest: dict,
    vault: str,
    prior: set | None = None,
    layout: str = "nested",
    index_link_mode: str = "auto",
    create_sortspec: bool = True,
) -> list:
    prior = prior or set()
    index_target = _library_index_target(vault, index_link_mode)
    src = manifest["source"]
    source_slug = src["source_slug"]
    title = clean_inline(src["title"])
    created = src["extracted_at"]
    file_name = src["file_name"]
    sections = manifest["sections"]
    # Defensive sanitization: a manifest produced before text-cleaning, or with
    # exotic source text, may carry control chars in titles/bodies.
    for s in sections:
        s["title"] = clean_inline(s.get("title", ""))
        s["display_title"] = clean_inline(s.get("display_title", ""))
        # Leaves always carry markdown; branches now may too (preamble body).
        if "markdown" in s:
            s["markdown"] = clean_block(s.get("markdown", ""))
    by_number = {s["toc_number"]: s for s in sections}
    paths = naming.compute_paths(sections, source_slug, layout=layout)
    # Page -> note map and per-note headings, used to linkify index entries.
    page_targets = _page_targets(sections, paths)
    headings_for = _headings_by_target(sections, paths)
    leaves = toc_tree.leaf_sequence(sections)
    leaf_order = {s["toc_number"]: i for i, s in enumerate(leaves)}
    owned: set = set()

    base_tags = ["pdf-import", source_slug]

    # --- section notes -------------------------------------------------------
    for node in sections:
        num = node["toc_number"]
        info = paths[num]
        meta = {
            "title": node["display_title"],
            "source": file_name,
            "source_pages": [node["start_page"], node["end_page"]],
            "boundary": "page-level",
            "toc_level": node["level"],
            "toc_number": num,
            "parent": _parent_link(node, by_number, paths, source_slug, title),
            "tags": base_tags,
            "created": created,
            "generated_by": GENERATED_BY,
        }

        if node["is_leaf"]:
            idx = leaf_order[num]
            if idx > 0:
                p = leaves[idx - 1]
                meta["prev"] = links.wikilink(
                    paths[p["toc_number"]]["link_target"], p["display_title"]
                )
            if idx < len(leaves) - 1:
                nx = leaves[idx + 1]
                meta["next"] = links.wikilink(
                    paths[nx["toc_number"]]["link_target"], nx["display_title"]
                )
            body = node.get("markdown", "").strip() or "_No extractable text in this section._"
            body = _resolve_assets(body, source_slug, info["dir"])
            if node.get("kind") == "index":
                body = _linkify_index_body(body, page_targets, headings_for)
            note = frontmatter.render_note(meta, body)
        else:
            children = toc_tree.children_of(sections, num)
            bullets = "\n".join(
                f"- {links.wikilink(paths[c['toc_number']]['link_target'], c['display_title'])}"
                for c in children
            )
            contents = f"## Contents\n\n{bullets}"
            # A branch may own preamble body (pages before its first child).
            # Render it under the folder-note title, above the Contents list.
            # The injected H1 is kept for navigational consistency; a near-
            # duplicate PDF heading in the preamble is faithful and left as-is.
            preamble = node.get("markdown", "").strip()
            if preamble:
                preamble = _resolve_assets(preamble, source_slug, info["dir"])
                body = f"# {node['display_title']}\n\n{preamble}\n\n{contents}"
            else:
                body = f"# {node['display_title']}\n\n{contents}"
            note = frontmatter.render_note(meta, body)

        _safe_write(vault, info["note_path"], note, owned, prior)

    # --- per-PDF MOC (folder note) ------------------------------------------
    top = toc_tree.children_of(sections, None)
    top_bullets = "\n".join(
        f"- {links.wikilink(paths[c['toc_number']]['link_target'], c['display_title'])}"
        for c in top
    )
    moc_meta = {
        "title": title,
        "source": file_name,
        "source_pages": [1, src["page_count"]],
        "boundary": "page-level",
        "toc_level": 0,
        "toc_number": "00",
        "parent": links.wikilink(index_target, "Imported PDFs"),
        "tags": base_tags,
        "created": created,
        "generated_by": GENERATED_BY,
    }
    # When the hierarchy was inferred from detected headings (no embedded ToC),
    # keep the Extracted-vs-Inferred distinction visible to the reader, not just
    # in the build log / manifest warnings.
    inferred_note = ""
    if manifest.get("toc_source") == "headings":
        inferred_note = (
            "> [!note] No embedded table of contents. This structure was "
            "inferred from detected headings, not extracted from PDF bookmarks "
            "- verify it matches the source before relying on it.\n\n"
        )
    moc_body = (
        f"# {title}\n\n"
        f"> Source: `{file_name}` - {src['page_count']} pages - imported {created}\n\n"
        f"{inferred_note}"
        f"## Contents\n\n{top_bullets}"
    )
    _safe_write(
        vault,
        naming.source_moc_path(source_slug),
        frontmatter.render_note(moc_meta, moc_body),
        owned,
        prior,
    )

    # --- assets --------------------------------------------------------------
    staging = src.get("assets_staging_dir")
    # Both leaves and branches (preamble) may reference assets now.
    referenced = {a["ref"] for s in sections for a in s.get("assets", [])}
    if staging and referenced:
        dest_dir = os.path.join(vault, naming.asset_dir(source_slug))
        os.makedirs(dest_dir, exist_ok=True)
        for name in sorted(referenced):
            src_file = os.path.join(staging, name)
            if os.path.exists(src_file):
                shutil.copy2(src_file, os.path.join(dest_dir, name))
                owned.add(f"{naming.asset_dir(source_slug)}/{name}")

    # --- library index (co-owned: managed region only) ---------------------
    _update_library_index(vault, source_slug, title)

    # --- File Explorer sort specs (user-owned; created once each) ----------
    if create_sortspec:
        _ensure_sortspec(vault)
        _ensure_book_sortspec(vault, source_slug)

    return sorted(owned)


def _ensure_sortspec(vault: str) -> None:
    """Scaffold a Custom-Sort spec so Obsidian's File Explorer interleaves files
    and folders (reading order by numeric prefix) instead of folders-first.

    Created once and never overwritten, so user edits survive rebuilds. It is
    deliberately NOT recorded as a generated (owned) file: it is user-owned,
    view-only config, exempt from the naming contract and orphan cleanup.
    """
    path = os.path.join(vault, naming.SORTSPEC)
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(naming.sortspec_note(naming.sortspec_target(vault)))


def _ensure_book_sortspec(vault: str, source_slug: str) -> None:
    """Scaffold a per-book recursive Custom-Sort spec inside the per-PDF folder.

    The library-level sortspec (created by ``_ensure_sortspec``) uses ``/*``
    which only covers the library root's immediate children. This companion
    spec uses ``/**`` to apply the same numeric-prefix ordering recursively
    through every nested subfolder in the book.

    Created once and never overwritten (user-owned, like the library spec).
    Not recorded as a generated file; survives orphan cleanup.
    """
    path = os.path.join(vault, source_slug, naming.SORTSPEC)
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    target = naming.sortspec_book_target(vault, source_slug)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(naming.sortspec_note(target))


def _update_library_index(vault: str, source_slug: str, title: str) -> None:
    index_path = os.path.join(vault, naming.LIBRARY_INDEX)
    existing = ""
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as fh:
            existing = fh.read()
    else:
        existing = "# Imported PDFs\n\n"

    entries = []
    for target, alias in links.extract_links(_managed_slice(existing)):
        entries.append((target, alias))
    # Upsert this PDF's entry. Drop ALL prior entries for this source, not just
    # the exact current target: an older build (or a different link convention)
    # may have written a bare `[[<slug>]]` instead of `[[<slug>/<slug>]]`, and
    # both share the same leading slug segment. Keying on that segment prevents
    # stale duplicates from accumulating in the managed region.
    moc_target = f"{source_slug}/{source_slug}"
    entries = [
        (t, a) for (t, a) in entries if t.split("/", 1)[0] != source_slug
    ]
    entries.append((moc_target, title))

    block = links.render_managed_block(entries)
    updated = links.upsert_managed_region(existing, block)
    os.makedirs(os.path.dirname(index_path) or ".", exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(updated if updated.endswith("\n") else updated + "\n")


def _remove_orphans(vault: str, orphans: list) -> int:
    """Delete previously-generated paths we no longer own; prune empty dirs."""
    removed = 0
    pruned_dirs = set()
    for rel in orphans:
        abs_path = os.path.join(vault, rel)
        if os.path.isfile(abs_path):
            os.remove(abs_path)
            removed += 1
            pruned_dirs.add(os.path.dirname(abs_path))
    # Prune now-empty directories, deepest first.
    for d in sorted(pruned_dirs, key=lambda p: p.count(os.sep), reverse=True):
        cur = d
        while os.path.isdir(cur) and os.path.abspath(cur) != os.path.abspath(vault):
            if os.listdir(cur):
                break
            os.rmdir(cur)
            cur = os.path.dirname(cur)
    return removed


def _managed_slice(text: str) -> str:
    if links.AUTO_START in text and links.AUTO_END in text:
        start = text.index(links.AUTO_START)
        end = text.index(links.AUTO_END)
        return text[start:end]
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an Obsidian vault from a manifest.")
    parser.add_argument("manifest")
    parser.add_argument("--vault", required=True, help="Vault output root")
    parser.add_argument(
        "--generated-dir", default=None, help="Where to write the generated-paths record (default: alongside manifest)"
    )
    parser.add_argument(
        "--layout",
        choices=["nested", "uniform"],
        default=None,
        help="Vault layout. 'nested' (default): branch sections are folders, "
        "leaf sections are files. 'uniform': every section is a folder note so "
        "Obsidian's explorer (folders-before-files) shows ToC order. Falls back "
        "to pipeline.config.json 'layout', then 'nested'.",
    )
    args = parser.parse_args()

    manifest = _load(args.manifest)
    os.makedirs(args.vault, exist_ok=True)

    cfg = {}
    cfg_path = os.path.join(os.getcwd(), "pipeline.config.json")
    if os.path.exists(cfg_path):
        try:
            cfg = _load(cfg_path)
        except (ValueError, OSError):
            cfg = {}

    layout = args.layout or cfg.get("layout")
    if layout not in ("nested", "uniform"):
        layout = "nested"

    index_link_mode = cfg.get("library_index_link", "auto")
    if index_link_mode not in ("auto", "root"):
        index_link_mode = "auto"

    create_sortspec = cfg.get("sortspec", True) is not False

    gen_dir = args.generated_dir or os.path.dirname(os.path.abspath(args.manifest))
    slug = manifest["source"]["source_slug"]
    gen_path = os.path.join(gen_dir, f"{slug}.generated.json")

    # Reclaim files we generated on a previous run (safe re-build / refresh).
    prior: set = set()
    prior_vault = None
    if os.path.exists(gen_path):
        try:
            rec = _load(gen_path)
            prior = set(rec.get("paths", []))
            prior_vault = rec.get("vault")
        except (ValueError, OSError):
            prior = set()

    # Warn if the vault has been moved/renamed since the last build: the orphan
    # cleanup below only ever touches paths under the *current* --vault, so the
    # files at the old location are left behind (silently stale). Surface it so
    # the user can clean up or re-point intentionally.
    if prior_vault and os.path.abspath(prior_vault) != os.path.abspath(args.vault):
        print(
            f"warning: this source was previously built into a different vault:\n"
            f"           previous: {prior_vault}\n"
            f"           current:  {os.path.abspath(args.vault)}\n"
            f"         Orphan cleanup only runs under the current vault; any files\n"
            f"         at the previous location are left untouched. Remove them\n"
            f"         manually if that vault is obsolete.",
            file=sys.stderr,
        )

    owned = build(
        manifest,
        args.vault,
        prior,
        layout=layout,
        index_link_mode=index_link_mode,
        create_sortspec=create_sortspec,
    )

    # Remove files we generated previously but no longer own (e.g. after a
    # layout switch or a ToC change). Only ever touches paths we recorded.
    orphans = sorted(prior - set(owned))
    removed = _remove_orphans(args.vault, orphans)

    with open(gen_path, "w", encoding="utf-8") as fh:
        json.dump({"vault": os.path.abspath(args.vault), "paths": owned}, fh, indent=2)

    print(f"Built {len(owned)} files into {args.vault} (layout: {layout})")
    if removed:
        print(f"Removed {removed} stale file(s) from the previous run")
    print(f"Recorded generated paths -> {gen_path}")


if __name__ == "__main__":
    main()
