"""Vault-relative path construction (vault-contract.md, sections 1, 2, 4).

All paths returned here are POSIX, relative to the vault root, so they double as
wikilink targets (just drop the ``.md``).
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

LIBRARY_INDEX = "index.md"
OBSIDIAN_DIR = ".obsidian"
SORTSPEC = "sortspec.md"


def _segment(node: dict) -> str:
    return f"{node['toc_number']}-{node['slug']}"


def _index_by_number(sections: List[dict]) -> Dict[str, dict]:
    return {s["toc_number"]: s for s in sections}


def _ancestors(node: dict, by_number: Dict[str, dict]) -> List[dict]:
    chain: List[dict] = []
    parent = node.get("parent_number")
    while parent is not None and parent in by_number:
        anc = by_number[parent]
        chain.append(anc)
        parent = anc.get("parent_number")
    chain.reverse()
    return chain


def source_moc_path(source_slug: str) -> str:
    """Per-PDF MOC (folder note)."""
    return f"{source_slug}/{source_slug}.md"


def asset_dir(source_slug: str) -> str:
    return f"{source_slug}/assets"


def compute_paths(
    sections: List[dict], source_slug: str, layout: str = "nested"
) -> Dict[str, dict]:
    """Map toc_number -> {note_path, dir, link_target}.

    ``note_path`` ends in ``.md``; ``link_target`` is the same without the
    extension (for wikilinks). Slug collisions within one directory are broken
    deterministically with ``-2``, ``-3`` suffixes.

    ``layout`` controls how leaf sections are placed:

    - ``"nested"`` (default): branch sections are folder notes; leaf sections
      are plain files alongside their siblings.
    - ``"uniform"``: *every* section is its own folder note. All entries at any
      level are therefore folders, so Obsidian's file explorer (which always
      lists folders before files) shows them in ToC order. See
      ``docs/vault-contract.md`` § Layout modes.
    """
    by_number = _index_by_number(sections)
    result: Dict[str, dict] = {}
    seen_per_dir: Dict[str, set] = {}

    for node in sections:
        anc_segments = [_segment(a) for a in _ancestors(node, by_number)]
        as_folder = layout == "uniform" or not node["is_leaf"]
        if as_folder:
            directory = "/".join([source_slug, *anc_segments, _segment(node)])
            stem = _segment(node)
        else:
            directory = "/".join([source_slug, *anc_segments])
            stem = _segment(node)

        seen = seen_per_dir.setdefault(directory, set())
        unique_stem = stem
        suffix = 2
        while unique_stem in seen:
            unique_stem = f"{stem}-{suffix}"
            suffix += 1
        seen.add(unique_stem)

        note_path = f"{directory}/{unique_stem}.md"
        result[node["toc_number"]] = {
            "note_path": note_path,
            "dir": directory,
            "link_target": note_path[: -len(".md")],
        }
    return result


def find_obsidian_root(vault_path: str) -> Optional[str]:
    """Nearest ancestor of `vault_path` (inclusive) containing a `.obsidian/`
    folder, or None if the vault is not inside an Obsidian vault."""
    cur = os.path.abspath(vault_path)
    while True:
        if os.path.isdir(os.path.join(cur, OBSIDIAN_DIR)):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:  # reached the filesystem root
            return None
        cur = parent


def obsidian_relative_index(vault_path: str) -> Optional[str]:
    """Wikilink target for this library's `index.md`, disambiguated for use
    inside a larger Obsidian vault.

    When the vault lives under an Obsidian root, return the Obsidian-root-
    relative path (e.g. ``Games/Bolt Action/.../index``) so multiple libraries
    in one Obsidian vault never collide on a bare ``[[index]]``. When the vault
    is *not* inside an Obsidian vault (standalone output), return None so the
    caller falls back to the bare ``index`` link (current behavior).
    """
    root = find_obsidian_root(vault_path)
    if root is None:
        return None
    rel = os.path.relpath(os.path.abspath(vault_path), root).replace(os.sep, "/")
    stem = LIBRARY_INDEX[: -len(".md")]
    if rel == ".":  # the vault root *is* the Obsidian root
        return stem
    return f"{rel}/{stem}"


def sortspec_target(vault_path: str) -> str:
    """`target-folder:` value for this library's Custom-Sort spec.

    Scopes the sorting rule to this library's own subtree so it never reorders
    unrelated folders in a larger Obsidian vault. When the vault sits under an
    Obsidian root, return the Obsidian-root-relative library path plus the ``/*``
    subtree wildcard (e.g. ``Games/Necromunda/Rules/*``). When the vault is the
    Obsidian root itself, or not inside an Obsidian vault, fall back to ``/*``
    (the whole vault -- which is just this library in the standalone case).

    Note: ``/*`` matches only the immediate children of the target folder.
    Use ``sortspec_book_target`` for the recursive per-book rule.
    """
    root = find_obsidian_root(vault_path)
    if root is None:
        return "/*"
    rel = os.path.relpath(os.path.abspath(vault_path), root).replace(os.sep, "/")
    if rel == ".":
        return "/*"
    return f"{rel}/*"


def sortspec_book_target(vault_path: str, source_slug: str) -> str:
    """`target-folder:` value for a per-book recursive Custom-Sort spec.

    Returns the Obsidian-root-relative path to the per-PDF subfolder with a
    ``/**`` wildcard, which the Custom-Sort plugin applies recursively to all
    nested subfolders (e.g. ``Study/Books/annex-project-pack-bible/**``).
    This ensures the numeric-prefix ordering applies at every depth of the
    book's nested folder hierarchy, not just its immediate children.

    Falls back to ``/<source_slug>/**`` when no Obsidian root is found.
    """
    root = find_obsidian_root(vault_path)
    if root is None:
        return f"/{source_slug}/**"
    rel = os.path.relpath(os.path.abspath(vault_path), root).replace(os.sep, "/")
    if rel == ".":
        return f"/{source_slug}/**"
    return f"{rel}/{source_slug}/**"


def sortspec_note(target: str) -> str:
    """Full text of the Custom-Sort spec note (frontmatter + human note).

    The ``sorting-spec`` frontmatter is read by the community plugin "Custom
    File Explorer sorting" (obsidian-custom-sort); ``order-asc: a-z`` makes the
    plugin treat files and folders equally, so notes list in reading order (by
    their numeric prefixes) instead of Obsidian's default folders-before-files.
    """
    return (
        "---\n"
        "sorting-spec: |-\n"
        f"  target-folder: {target}\n"
        "  order-asc: a-z\n"
        "---\n\n"
        "Interleaves files and folders in Obsidian's File Explorer so notes "
        "appear in reading order (by their numeric prefixes) instead of "
        "Obsidian's default folders-before-files.\n\n"
        "Requires the community plugin \"Custom File Explorer sorting\" "
        "(obsidian-custom-sort). View-only: nothing on disk changes.\n"
    )


def relative_asset_ref(source_slug: str, note_dir: str, asset_name: str) -> str:
    """Markdown image path from a note to an asset.

    Notes can be nested, so compute a path back up to the per-PDF ``assets/``
    folder. Returns a POSIX relative path suitable for ``![](...)``.
    """
    depth_below_source = note_dir.count("/")  # source_slug is one segment => 0 extra
    ups = "../" * depth_below_source
    return f"{ups}assets/{asset_name}"
