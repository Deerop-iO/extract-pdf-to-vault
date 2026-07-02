# tools/

Development and maintenance artifacts — not part of the kit itself.

- `clean_existing_vault.py` — maintenance script for wiping a vault subtree
  (removes only files marked `generated_by: p2v`).
- `frostgrave-backup/`, `frostgrave-backup-pass2/` — snapshots of test builds
  used during Phase 1 development (gitignored; not present in a clean clone).
- `frostgrave-report.json`, `frostgrave-report-pass2.json` — `verify_vault.py`
  output from those test runs (gitignored).
- `frostgrave.patterns` — patterns file for `clean_existing_vault.py`
  (gitignored; may contain ownership watermarks).

None of these files are required to run the pipeline.
