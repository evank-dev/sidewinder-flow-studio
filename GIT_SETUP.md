# Publishing SFS to GitHub — step by step

## 0. Before anything: get the LICENSE file

I couldn't download the AGPL-3.0 text (no network access), and a license must be
the **verbatim official text** — don't let anyone paraphrase it.

Easiest route: when you create the repo on GitHub, pick **"GNU Affero General
Public License v3.0"** from the *Add a license* dropdown. GitHub writes the
correct `LICENSE` file for you.

If you create the repo empty instead, download it:

```bash
curl -o LICENSE https://www.gnu.org/licenses/agpl-3.0.txt
```

`LICENSE.header.txt` in this repo holds the copyright notice to paste at the top
of the README or source headers if you want it — it is NOT a substitute for the
full LICENSE file.

---

## 1. Safety check — never commit secrets

```bash
cd /path/to/flow-studio

# These must print nothing (they're ignored). If any file shows, STOP.
git status --porcelain --ignored=no 2>/dev/null | grep -E "\.env$|\.env\.|\.db$|\.duckdb|node_modules|projects/|frame_cache" 

# Confirm your real .env is ignored
git check-ignore -v .env backend/.env
```

Your `SECRET_KEY` lives in `.env`. If it ever lands in a commit, it's in the
history forever — rotate it and rewrite history. Far easier to check now.

---

## 2. Initialise and make the first commit

```bash
cd /path/to/flow-studio

git init
git branch -M main

git add .
git status          # ← READ THIS LIST. No .env, no *.db, no node_modules, no zips.

git commit -m "Initial public release — Sidewinder Flow Studio v1.10

Visual Python/SQL ETL on a canvas with Arrow between nodes.
Five engines (pandas, Polars, DuckDB, SQL pushdown, Ibis), 17 connectors,
native bulk loading, reports, profiling, AI-assisted authoring, and a
documented plugin contract for adding engines."
```

---

## 3. Create the GitHub repo

On github.com → **New repository**:

- Name: `sidewinder-flow-studio` (or `sfs` — pick one and keep it)
- Description: *Visual ETL where every node is a Python or SQL cell. Arrow between nodes, five engines, warehouse pushdown.*
- **Public**
- Do **not** add a README or .gitignore (you have them)
- **Do** add the AGPL-3.0 license (see step 0)

Then connect and push:

```bash
git remote add origin https://github.com/YOUR_USERNAME/sidewinder-flow-studio.git
git pull --rebase origin main      # picks up the LICENSE GitHub created
git push -u origin main
```

---

## 4. Tag the release

```bash
git tag -a v1.10 -m "v1.10 — initial public release"
git push origin v1.10
```

Then on GitHub → Releases → *Draft a new release* → choose tag `v1.10` → paste
the highlights from the commit message.

---

## 5. Polish the repo page (10 minutes, high impact)

- **About** (right sidebar, gear icon): add the one-line description and topics —
  `etl`, `data-engineering`, `python`, `duckdb`, `polars`, `pandas`, `dataops`,
  `visual-programming`, `arrow`, `self-hosted`
- **Add a GIF to the README.** This matters more than anything else on the page:
  record 15 seconds of dragging nodes → running → inspecting data → a dashboard.
  Drag the file into a GitHub issue comment to get a URL, then use that URL in
  the README where the TODO comment is.
- Enable **Issues** and **Discussions** (Settings → Features)

---

## 6. Day-to-day from here

```bash
git checkout -b feature/thing
# ...make changes...
git add -A && git commit -m "Add thing"
git push -u origin feature/thing
# open a PR, or just merge to main if you're working solo:
git checkout main && git merge feature/thing && git push
```

For releases, bump the version in all four places (they must match):

- `backend/pyproject.toml` → `version = "..."`
- `backend/app/core/app_factory.py` → `version="..."`
- `frontend/package.json` → `"version": "..."`
- `frontend/src/components/ui/AboutDialog.tsx` → `SFS_VERSION = '...'`

then commit, tag, and push the tag.

---

## 7. If you ever split out a private enterprise repo

Don't fork the whole codebase — that creates a permanent sync burden. Instead,
create a separate private repo containing **only** enterprise plugin packages
that depend on the public one and register via the `sfs.plugins` entry point
(see `docs/PLUGINS.md`). The shared core stays in exactly one place.
