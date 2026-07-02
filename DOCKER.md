# Docker Installation and Usage Guide

Run the pdf-to-vault pipeline **without installing Python**. Docker packages the
pinned runtime (Python 3.11, PyMuPDF, pymupdf4llm, PyYAML) into a portable image;
your PDFs, config, and vault output stay on your machine.

**Repository:** https://github.com/Deerop-iO/extract-pdf-to-vault

---

## Table of contents

1. [Quick start](#quick-start)
2. [When to use Docker](#when-to-use-docker)
3. [Prerequisites](#prerequisites)
4. [Architecture](#architecture)
5. [Installation](#installation)
6. [Project setup](#project-setup)
7. [Usage](#usage)
8. [Using with Cursor or Claude Code](#using-with-cursor-or-claude-code)
9. [Updating the image](#updating-the-image)
10. [Sharing with colleagues](#sharing-with-colleagues)
11. [Security and data handling](#security-and-data-handling)
12. [Troubleshooting](#troubleshooting)
13. [Platform notes](#platform-notes)
14. [Reference: without the wrapper script](#reference-without-the-wrapper-script)

---

## Quick start

For experienced Docker users — full detail in the sections below.

```bash
# 1. Clone and build (once, from the kit folder)
git clone https://github.com/Deerop-iO/extract-pdf-to-vault.git
cd extract-pdf-to-vault
docker build -t p2v .

# 2. Prepare a project folder (PDF + config live here)
mkdir -p ~/my-pdf-project && cd ~/my-pdf-project
cp /path/to/extract-pdf-to-vault/docker-run.sh .
chmod +x docker-run.sh

# 3. Run the pipeline (from the project folder; Docker Desktop must be running)
./docker-run.sh extract "my-book.pdf" --out .p2v --config pipeline.config.json
./docker-run.sh build ".p2v/my-book.manifest.json" --vault "./my-vault"
./docker-run.sh verify --vault "./my-vault" --config verify.config.json
```

Verify success: the last command prints `PASS` for all enabled gates.

---

## When to use Docker

| Use Docker when… | Use Python (venv) when… |
|---|---|
| You do not have Python installed | You already have Python 3.10+ set up |
| You want identical deps across machines | You are developing or patching the kit |
| You are onboarding non-developers | You run the kit `tests/` locally |

Both paths run the **same scripts** with the **same flags**. Only the invocation
changes (`./docker-run.sh extract …` vs `python scripts/extract.py …`).

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Docker Desktop** (macOS / Windows) or **Docker Engine** (Linux) | Latest stable release recommended |
| **Git** | To clone the repository |
| **~2 GB free disk** | Image is ~400–500 MB; build cache and vault output need space |
| **Network** (first build only) | Pulls `python:3.11-slim` and pip packages; runs are offline |

No API keys, cloud accounts, or Python installation required.

---

## Architecture

Two folders, two roles — the most important concept for Docker users:

| Folder | Role | You run… |
|---|---|---|
| **Kit folder** (`extract-pdf-to-vault/`) | Contains `Dockerfile`, pipeline templates, agent skills | `docker build -t p2v .` (once per kit version) |
| **Project folder** | Contains your PDF, `pipeline.config.json`, vault output | `./docker-run.sh …` (every conversion) |

**How the mount works:** `docker-run.sh` bind-mounts your **current project
folder** to `/vault` inside the container. The container reads the PDF and config
from that mount and writes manifests and vault notes back to it. Nothing is copied
into the image at run time; the container is ephemeral (`--rm`).

```
Your Mac                          Docker container (p2v)
─────────────────                 ─────────────────────────
~/my-pdf-project/  ── mount ──►  /vault/
  my-book.pdf                       reads PDF, writes .p2v/ and my-vault/
  pipeline.config.json
  docker-run.sh
```

**Constraint:** paths in config must stay **inside** the project folder (e.g.
`./my-vault`). Paths like `../pdf-vault-output` escape the mount and fail.

---

## Installation

### Step 1 — Install Docker

**macOS / Windows:** install [Docker Desktop](https://www.docker.com/products/docker-desktop),
launch it, and wait until the menu-bar / system-tray whale icon is steady (engine
running).

**Linux:** install [Docker Engine](https://docs.docker.com/engine/install/) and
ensure your user can run Docker (`docker run hello-world` succeeds).

### Step 2 — Clone the repository

```bash
git clone https://github.com/Deerop-iO/extract-pdf-to-vault.git
cd extract-pdf-to-vault
```

Optional: check out a release tag for a known-good version:

```bash
git checkout v1.0.1
```

### Step 3 — Build the image

From the **kit folder** (where the `Dockerfile` lives):

```bash
docker build -t p2v .
```

- **First build:** several minutes (downloads base image + installs PyMuPDF).
- **Later builds:** seconds if nothing changed (Docker layer cache).
- **Rebuild when:** `templates/requirements.txt` changes (kit upgrade).

The tag `p2v` is the local name `docker-run.sh` expects. You can add a version
tag alongside it:

```bash
docker tag p2v p2v:1.0.1
```

### Step 4 — Verify the installation

Confirm the image exists:

```bash
docker image ls p2v
```

Smoke-test the entrypoint (no PDF needed):

```bash
docker run --rm p2v verify --help
```

You should see `verify_vault.py` usage text. If you get `Cannot connect to the
Docker daemon`, start Docker Desktop and retry.

---

## Project setup

The pipeline config and PDFs live in a **project folder**, separate from the kit.

### Option A — Agent-guided setup (recommended)

1. Open the cloned kit in **Cursor** or **Claude Code**.
2. Run `/p2v-start-project` and choose the Docker path when prompted.
3. When asked for `vault_output`, use a path **inside** the project folder, e.g.
   `./pdf-vault-output` (not `../pdf-vault-output`).
4. Copy `docker-run.sh` from the kit into the scaffolded project folder:

   ```bash
   cp /path/to/extract-pdf-to-vault/docker-run.sh /path/to/your-project/
   chmod +x /path/to/your-project/docker-run.sh
   ```

### Option B — Manual setup

1. Create a project folder and copy templates from the kit:

   ```bash
   mkdir -p ~/my-pdf-project && cd ~/my-pdf-project
   cp -r /path/to/extract-pdf-to-vault/templates/scripts .
   cp /path/to/extract-pdf-to-vault/templates/pipeline.config.json .
   cp /path/to/extract-pdf-to-vault/templates/verify.config.json .
   cp /path/to/extract-pdf-to-vault/docker-run.sh .
   chmod +x docker-run.sh
   ```

2. Edit `pipeline.config.json` — set `vault_output` to a in-folder path:

   ```json
   {
     "vault_output": "./pdf-vault-output"
   }
   ```

3. Place your PDF in the project folder (or note its absolute path if outside —
   prefer keeping PDFs inside the project folder for Docker).

---

## Usage

Always run commands from your **project folder**. Docker Desktop must be running.

### Standard workflow (extract → build → verify)

Replace `my-book.pdf` and manifest slug with your actual filenames.

```bash
cd ~/my-pdf-project

# 1. Extract PDF → manifest (source of truth)
./docker-run.sh extract "my-book.pdf" \
  --out .p2v \
  --config pipeline.config.json

# 2. Build Obsidian vault from manifest
./docker-run.sh build ".p2v/my-book.manifest.json" \
  --vault "./pdf-vault-output"

# 3. Verify contract compliance (blocking)
./docker-run.sh verify \
  --vault "./pdf-vault-output" \
  --config verify.config.json
```

Open `./pdf-vault-output` in Obsidian when verify reports PASS.

### Subcommands

| Subcommand | Script | Purpose |
|---|---|---|
| `extract` | `extract.py` | PDF → `.p2v/<slug>.manifest.json` |
| `build` | `build_vault.py` | manifest → vault notes, MOCs, assets |
| `verify` | `verify_vault.py` | contract gates (frontmatter, links, assets…) |
| `enrich` | `apply_enrichment.py` | post-build summaries + topic tags (optional) |
| `repair` | `apply_repair.py` | guard-gated table/index repair (optional) |

### Common extract flags

Append to the `extract` command as needed:

| Flag | When to use |
|---|---|
| `--fallback toc` | No embedded ToC; use printed contents page |
| `--fallback headings` | No ToC; flat hierarchy from page headings |
| `--fallback pages` | No ToC; one note per page |
| `--write-images` | PDF has diagrams or figures worth keeping |
| `--ignore-toc` | Embedded ToC is degenerate (requires `--fallback`) |

Example:

```bash
./docker-run.sh extract "scanned-layout.pdf" \
  --out .p2v \
  --config pipeline.config.json \
  --fallback headings \
  --write-images
```

If extraction reports the PDF **looks scanned**, stop — OCR is opt-in and not
included in the default image.

### Enrich and repair (optional, post-build)

```bash
./docker-run.sh enrich "pdf-vault-output/my-slug/01-intro/01-intro.md" \
  --summary "One faithful line from the note body." \
  --add-tags "topic/example,enriched"

./docker-run.sh repair "pdf-vault-output/my-slug/…/note.md" \
  --kind table --new-body after.md
```

These steps are normally driven by `/p2v-enrich-document` and
`/p2v-repair-document` in your AI editor.

---

## Using with Cursor or Claude Code

1. Clone the kit and build the image (installation steps above).
2. Open the kit or your project in Cursor / Claude Code.
3. The agent loads `AGENTS.md` or `CLAUDE.md` automatically.
4. Run slash commands — workflow skills include Docker command variants:

   | Command | Action |
   |---|---|
   | `/p2v-start-project` | Scaffold project + config |
   | `/p2v-build-document` | Extract → build → verify one PDF |
   | `/p2v-verify-vault` | Re-run verification gates |

The agent runs `./docker-run.sh …` instead of `python scripts/…` when Docker is
the chosen runtime.

---

## Updating the image

When a new kit version is released:

```bash
cd extract-pdf-to-vault
git pull
git checkout v1.0.1   # or latest tag
docker build -t p2v .
```

Rebuild is required only when `templates/requirements.txt` or `Dockerfile`
changes. Config and workflow changes in the repo do not require a rebuild unless
you rely on scripts baked into the image (the project folder’s copied `scripts/`
are used only on the Python path; Docker uses `/app/scripts/` inside the image).

---

## Sharing with colleagues

### Recommended — share the repository

Colleagues clone and build locally. Same Dockerfile and pinned requirements
guarantee a reproducible environment:

```bash
git clone https://github.com/Deerop-iO/extract-pdf-to-vault.git
cd extract-pdf-to-vault
docker build -t p2v .
```

Point them to this document (`DOCKER.md`).

### Optional — export a tarball (offline, no registry)

**Maintainer:**

```bash
docker save p2v -o p2v-1.0.1.tar
# Transfer p2v-1.0.1.tar securely (size ~400+ MB)
```

**Colleague:**

```bash
docker load -i p2v-1.0.1.tar
docker image ls p2v   # confirm loaded
```

Also share `docker-run.sh` and this guide. Re-export when dependencies change.

### Optional — publish to a container registry

For pull-only onboarding (no local build):

```bash
# Maintainer (example: Docker Hub)
docker tag p2v yourorg/p2v:1.0.1
docker push yourorg/p2v:1.0.1

# Colleague
docker pull yourorg/p2v:1.0.1
docker tag yourorg/p2v:1.0.1 p2v
```

The kit does **not** publish an official pre-built image by default; teams opt in
to a registry if they want centralized distribution.

---

## Security and data handling

- **Local-only processing:** PDFs and vault output are read/written via the
  bind mount on your machine. The default pipeline sends no document content to
  external services.
- **Ephemeral containers:** `--rm` removes the container after each run; no
  persistent container state.
- **Mount scope:** Only the project folder you run from is visible inside the
  container. Do not mount sensitive system directories as the project root.
- **Image contents:** Built from `python:3.11-slim` plus pinned pip packages in
  `templates/requirements.txt`. Review the `Dockerfile` and `.dockerignore` before
  building in regulated environments.
- **Secrets:** Phase 1 needs no API keys. If you add Phase 2 enrichment providers
  later, pass secrets via env files mounted at run time — never bake them into the
  image.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop not running | Launch Docker Desktop; wait for ready state |
| `docker: command not found` | Docker not installed or PATH issue | Install Docker Desktop; restart terminal |
| `permission denied: ./docker-run.sh` | Execute bit missing | `chmod +x docker-run.sh` |
| `Unable to find image 'p2v'` | Image not built | `docker build -t p2v .` from kit folder |
| Vault empty / wrong location | `vault_output` uses `../` | Set `"vault_output": "./pdf-vault-output"` |
| `No such file: scripts/extract.py` | Wrong invocation | Use `./docker-run.sh extract …`, not `scripts/extract.py` inside Docker |
| Build very slow first time | Normal | PyMuPDF native libs; later builds use cache |
| Verify FAIL after build | Contract or extraction issue | Read gate messages; re-run build — do not hand-edit generated notes to pass gates |

For pipeline-specific errors (no ToC, scanned PDF, safe-write refusal), follow
the messages in the workflow skills or `docs/vault-contract.md`.

---

## Platform notes

| Platform | Notes |
|---|---|
| **macOS (Apple Silicon)** | Native arm64 layers; no extra flags |
| **macOS (Intel)** | Supported via Docker Desktop |
| **Windows** | Use Docker Desktop with WSL 2 backend; run `docker-run.sh` from Git Bash or WSL |
| **Linux** | Docker Engine; ensure your user is in the `docker` group |

File paths in examples use Unix style (`./my-vault`). On Windows under WSL, use
Linux paths inside the WSL project folder.

---

## Reference: without the wrapper script

Equivalent to `./docker-run.sh extract "book.pdf" --out .p2v --config pipeline.config.json`:

```bash
docker run --rm \
  -v "$(pwd):/vault" \
  -w /vault \
  p2v extract "book.pdf" --out .p2v --config pipeline.config.json
```

The wrapper exists to avoid repeating the volume and working-directory flags.
