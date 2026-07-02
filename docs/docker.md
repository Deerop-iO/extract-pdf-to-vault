# Running pdf-to-vault with Docker

Docker lets colleagues run the pipeline without installing Python, a virtual
environment, or any dependencies. The container is a sealed, portable Python
environment; your PDF and vault files stay on your own Mac.

---

## Two folders, two roles

This is the one concept worth understanding before you start:

| Folder | What it is | What you do there |
|---|---|---|
| **Kit folder** — `extract-pdf-to-vault-agent/` | This repo. Contains the pipeline scripts and the `Dockerfile`. | Build the Docker image once. |
| **Project folder** — wherever your PDF and vault live | Your working directory. Contains `pipeline.config.json`. | Run every pipeline command from here. |

---

## One-time setup (done once, from the KIT folder)

### 1. Install Docker Desktop

Download and install from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop).
After installation, launch Docker Desktop. You will see a whale icon in the Mac
menu bar when it is running.

### 2. Build the image

Open a terminal, navigate to the kit folder, and run:

```bash
cd path/to/extract-pdf-to-vault-agent
docker build -t p2v .
```

This downloads Python 3.11 and installs the pinned pipeline dependencies
(PyMuPDF, pymupdf4llm, PyYAML). It takes a few minutes the first time; subsequent
builds are fast because Docker caches the layers.

**Only rebuild when `templates/requirements.txt` changes** (i.e. when the kit is
updated with new dependency versions).

### 3. Copy `docker-run.sh` to your project folder

```bash
cp docker-run.sh path/to/your-project-folder/
```

Or keep a reference to the kit's copy — either works.

---

## Every-day use (from your PROJECT folder)

Make sure Docker Desktop is running (check the menu-bar whale icon), then:

```bash
# 1. Extract the PDF into a manifest
./docker-run.sh extract "my-book.pdf" --out .p2v --config pipeline.config.json

# 2. Build the vault from the manifest
./docker-run.sh build ".p2v/my-book.manifest.json" --vault "./my-vault"

# 3. Verify the vault
./docker-run.sh verify --vault "./my-vault" --config verify.config.json
```

These are identical to the Python commands in the workflow skills, with
`./docker-run.sh <subcommand>` replacing `python scripts/<script>.py`.

### Available subcommands

| Subcommand | Runs |
|---|---|
| `extract` | `scripts/extract.py` |
| `build` | `scripts/build_vault.py` |
| `verify` | `scripts/verify_vault.py` |
| `enrich` | `scripts/apply_enrichment.py` |
| `repair` | `scripts/apply_repair.py` |

---

## Important: vault path must stay inside your project folder

When Docker runs, it shares your project folder with the container as `/vault`.
Paths that go *above* your project folder (e.g. `"../pdf-vault-output"`) escape
the mount and will fail.

**In `pipeline.config.json`, set `vault_output` to a path that starts with `./`:**

```json
"vault_output": "./pdf-vault-output"
```

Not:
```json
"vault_output": "../pdf-vault-output"   ← breaks with Docker
```

---

## Troubleshooting

**"Cannot connect to the Docker daemon"** — Docker Desktop is not running.
Launch it from Applications and wait for the menu-bar whale to appear.

**"docker: command not found"** — Docker Desktop is not installed, or the shell
does not have Docker in its PATH. Re-install Docker Desktop and restart the
terminal.

**"permission denied: ./docker-run.sh"** — The execute bit is not set. Fix with:
```bash
chmod +x docker-run.sh
```

**Build is slow the first time** — Normal. PyMuPDF includes native PDF libraries
(~400 MB image). Subsequent builds reuse the cached layer and are fast.

**On Apple Silicon (M1/M2/M3)** — The image works natively; no extra flags needed.
Docker Desktop on Apple Silicon pulls the arm64 layer of `python:3.11-slim`
automatically.
