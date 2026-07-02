---
name: p2v-verify-vault
description: Run the consistency harness against a generated Obsidian vault (frontmatter schema, filenames, link integrity, asset existence, reachability) and report failures. Trigger with /p2v-verify-vault.
disable-model-invocation: true
---

# /p2v-verify-vault

Check that a generated vault still satisfies the contract.

## Steps

1. **Scope.** Confirm the vault path (`vault_output` from `pipeline.config.json`)
   and which gates are enabled in `verify.config.json`.

2. **Run.**
   ```
   python scripts/verify_vault.py --vault "<vault_output>" --config verify.config.json
   ```
   With Docker:
   ```
   ./docker-run.sh verify --vault "<vault_output>" --config verify.config.json
   ```

3. **Report.**
   - On PASS: state which gates ran.
   - On FAIL: list each `[gate] path: message`, then explain the likely cause by
     gate:
     - `frontmatter` — a note missing keys or with wrong shapes (often a
       hand-edit or a stale build).
     - `filenames` — a note not matching the naming contract.
     - `links` — a bare or unresolved wikilink (link must be vault-relative +
       aliased).
     - `assets` — a referenced image missing on disk, or a surviving `ASSET:`
       sentinel.
     - `reachability` — an orphaned generated note not linked from the library
       index.

4. **Fix discipline.** Prefer fixing the **cause** (re-run the build, correct the
   contract/pipeline) over hand-editing generated notes. If a user genuinely
   hand-authored a note in the tree, point out it lacks `generated_by: p2v` and
   is outside the kit's ownership.

## Guardrails

- The harness is read-only; never let "make it pass" tempt you into editing
  generated notes by hand.
- Do not disable a gate to hide a real failure; if a gate is wrong, fix the gate
  and the contract together.
