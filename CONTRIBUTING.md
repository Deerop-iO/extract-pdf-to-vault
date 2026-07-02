# Contributing

How to extend this kit without causing drift.

## The golden rule: one fact, one owner

The structure + naming + frontmatter + wikilink contract lives in **one** place:
[`docs/vault-contract.md`](docs/vault-contract.md). Rules and references *cite*
it; they must not restate the field list or the slug algorithm. `verify_vault.py`
enforces exactly what the contract says. If you change the contract, update the
harness and the kit `tests/` in the same change.

## Layers

- `.cursor/rules/*.mdc` — always-on, broad discipline. Keep them short.
- `.cursor/skills/pdf-to-vault-agent/references/*.md` — load-on-demand depth.
- `.cursor/skills/pdf-to-vault-agent/workflows/*/SKILL.md` — step-by-step
  procedures, one per `/p2v-*` command, each `disable-model-invocation: true`.
- `templates/` — copied into the sibling vault project. Never put generated
  vault content here.

## Pipeline code

- Keep `templates/scripts/lib/` **pure** (no PDF/network I/O) so the kit `tests/`
  can exercise it directly.
- Determinism is a feature: pure slugify, positional ToC numbers, sorted
  traversal. Any change must keep two builds of the same manifest byte-identical
  (modulo `created`).
- Pins in `templates/requirements.txt` back the determinism guarantee. Bump them
  deliberately, then re-run `tests/` and a smoke build.

## Before you commit

1. `python -m pytest tests/` (or `python -m unittest`) passes.
2. A smoke build of a real PDF passes `verify_vault.py`.
3. `CHANGELOG.md` `## [Unreleased]` updated.

## Safety

- Never overwrite user-authored notes: respect `generated_by: p2v` + the
  generated-paths record.
- Never commit `.env` or a real vault's contents into this kit.
