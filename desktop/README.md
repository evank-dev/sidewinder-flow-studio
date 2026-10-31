# SFS Desktop

The installable, single-user edition of Sidewinder Flow Studio: no Docker, no
terminal, no Python install. Same repository and code as the server edition.

**Status: Phase 1.** Built for Linux, Windows and macOS (Apple Silicon) in CI;
unsigned. Signing, updates and the first-run screen come in later phases.

## How it works

```
Tauri v2 shell (src-tauri/)          native window, installer
   │ starts with --data-dir <OS app-data dir>, stops when the app exits
   ▼
backend sidecar (sidecar/)           SFS's FastAPI app frozen with PyInstaller
   │ serves the built frontend AND the API on 127.0.0.1:<free port>
   │ prints "SFS_READY port=<n>" when ready
   ▼
the window loads http://127.0.0.1:<n>/   (same origin as the API and WebSocket)
```

- `backend/app/desktop.py` is the backend's entry point: it points the usual
  settings (`PROJECTS_DIR`, `FRAME_CACHE_DIR`, …) at the data directory through
  environment variables, creates `secret.key` (owner-only) on first launch,
  binds a free port on 127.0.0.1 only, prints the ready line, and exits when its
  stdin closes, so it never outlives the shell, even if the shell is killed.
- The shell (`src-tauri/src/main.rs`) shows a loading page (`shell/`), waits up
  to 90 s for the ready line, then navigates the window to the backend. If the
  backend fails, the page shows the error and the end of the log. A second
  launch focuses the running window.
- Data lives in the OS app-data directory (Linux:
  `~/.local/share/dev.sidewinderlabs.flowstudio/`): `projects/`, `frame_cache/`,
  `flow_studio.db`, `secret.key`, and `logs/backend.log`. **Back up
  `secret.key`**: it encrypts saved connection passwords.

## CI

`.github/workflows/desktop.yml` builds every platform: Linux x64 (AppImage,
.deb, on Ubuntu 22.04 for an older glibc), Windows x64 (NSIS, MSI) and macOS
arm64 (DMG). Run it from the Actions tab (installers attached to the run), or
push a `v*` tag (installers also go to a draft release for that tag).

Each job runs the launcher tests, freezes the backend, and runs
`sidecar/smoke_test.py` twice: on the frozen backend, then on the copy inside
the built app. The smoke test waits for the ready line, checks every engine is
available, runs a flow through pandas, DuckDB, Polars and SQL, compiles an
Explore query, and checks the backend exits when stdin closes.

Platform settings live in `tauri.windows.conf.json` and `tauri.macos.conf.json`,
which Tauri merges over `tauri.conf.json`. macOS builds are ad-hoc signed
(`signingIdentity: "-"`) so they run on Apple Silicon; until Phase 2 adds
notarisation, the first launch needs right-click → Open.

## Build (Linux)

Requirements: Rust, Node 22, WebKitGTK 4.1 development files, and a Python 3.13
environment (a clean one keeps the bundle small).

```bash
# 1. the frontend
cd frontend && npm install && npm run build && cd ..

# 2. the backend sidecar (dist/sfs-backend/)
python -m pip install "./backend[pushdown]" ./plugins/sfs-plugin-curvefit pyinstaller
cd desktop/sidecar && pyinstaller --noconfirm sfs-backend.spec && cd ../..

# 3. check it, then build the app and installers (AppImage, .deb) in
#    src-tauri/target/release/bundle/
python desktop/sidecar/smoke_test.py desktop/sidecar/dist/sfs-backend/sfs-backend
cd desktop && npm install && npx tauri build
```

Plugins bundled in-process are listed in `SFS_DESKTOP_PLUGINS` (default
`curvefit`), like `SFS_PLUGINS` for Docker. For a quick development loop, build
the shell with `cargo build` in `src-tauri/` and point it at the sidecar with
`SFS_BACKEND=$PWD/sidecar/dist/sfs-backend/sfs-backend`.

## What is and isn't included

Bundled: the pandas, Polars, DuckDB, SQL and Ibis engines, PostgreSQL and
SQLite, Explore (including live queries on a connection, through SQLGlot), the
curve-fitting plugin, and the libraries node code commonly imports (NumPy,
pandas, PyArrow, SciPy, matplotlib, seaborn, Plotly, Polars, DuckDB, SQLGlot,
Ibis). Node code can import only what is bundled: there is no Python to
`pip install` into.

Not included: the Report node (Streamlit; hidden in the UI, since Explore
covers interactive charts), the isolated plugin runtime, the warehouse
connectors, multi-user features.

Optional settings (for example `ANTHROPIC_API_KEY` for the AI assistant) go in
a `.env` file in the data directory. A `.env` in the folder the app is
launched from is never read.

## Known issues

- **WebKitGTK on NVIDIA:** the DMA-BUF renderer leaves parts of the page
  unpainted, so the shell sets `WEBKIT_DISABLE_DMABUF_RENDERER=1` on Linux
  unless you set it yourself.
- **Launching from a snap-packaged terminal (e.g. VS Code's):** the snap's
  `GTK_PATH`/`GIO_MODULE_DIR` break WebKitGTK. Unset them, or start the app
  from the desktop.
- Downloads and native file dialogs inside the window are untested.
