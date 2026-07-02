# .claude/

Claude Code support files for the pdf-to-vault kit.

## commands/

Custom slash commands that give Claude Code users the same `/p2v-*` workflow
shortcuts as Cursor users. Each file maps one command to the corresponding
workflow skill:

| Command | Workflow skill |
|---|---|
| `/p2v-start-project` | `.cursor/skills/pdf-to-vault-agent/workflows/p2v-start-project/SKILL.md` |
| `/p2v-build-document` | `.cursor/skills/pdf-to-vault-agent/workflows/p2v-build-document/SKILL.md` |
| `/p2v-verify-vault` | `.cursor/skills/pdf-to-vault-agent/workflows/p2v-verify-vault/SKILL.md` |
| `/p2v-enrich-document` | `.cursor/skills/pdf-to-vault-agent/workflows/p2v-enrich-document/SKILL.md` |
| `/p2v-repair-document` | `.cursor/skills/pdf-to-vault-agent/workflows/p2v-repair-document/SKILL.md` |

The workflow skill files are the single source of truth for each procedure.
These command files are thin pointers — if a workflow changes, only the skill
file needs updating.

## Entry point

Claude Code auto-loads `CLAUDE.md` from the repo root at session start.
