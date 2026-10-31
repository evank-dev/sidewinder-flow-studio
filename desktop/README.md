# SFS Desktop

The installable, single-user edition of Sidewinder Flow Studio: no Docker, no
terminal, no Python install. Same repository and code as the server edition.

**Status: Phase 2.** Built for Linux, Windows and macOS (Apple Silicon) in CI,
with self-updates and code signing wired in (each switched on by repository
secrets, see "Releases and signing"). The first-run screen comes next.

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
which Tauri merges over `tauri.conf.json`. Without an Apple certificate, macOS
builds are ad-hoc signed (`signingIdentity: "-"`) so they run on Apple Silicon,
but the first launch needs right-click → Open.

## Updates

On launch the app fetches
`github.com/sidewinder-labs/sidewinder-flow-studio/releases/latest/download/latest.json`
(`src/update.rs`). If a newer version is listed it asks "Install and restart?";
on yes it downloads the package, checks its signature against the public key in
`tauri.conf.json` (`plugins.updater.pubkey`), stops the backend, installs and
restarts. Projects and settings live in the data directory, so they are kept.
Failures (offline, bad signature) go to `logs/update.log` and never block the
app.

- `latest.json` is written by CI (`scripts/latest_json.py`) and attached to the
  draft release. `releases/latest` only points at published releases, so
  nothing is offered until you publish the draft.
- Updatable: the AppImage, both Windows installers, the macOS app. A `.deb`
  install is left to the package manager (no check).
- `SFS_NO_UPDATE_CHECK=1` turns the check off; `SFS_AUTO_UPDATE=1` installs
  without asking (managed machines).
- Tested on Linux with two locally signed AppImages: update installed and the
  app restarted on the new version; a package whose signature didn't match was
  refused (and the app kept running); offline, the app starts normally.

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

## Releases and signing

A release is: bump the version (six files, `scripts/check_version.sh`), push
a `vX.Y` tag, wait for the Desktop workflow, review the draft release, publish.
Every signing step below is optional and switched on by its secrets
(Settings → Secrets and variables → Actions); without them the release is
unsigned but works.

### Key storage

**Signing keys never go in the repository** (`.gitignore` already excludes
`*.key`, `*.pem` and `.env`). Each key lives in two places only: the GitHub
Actions secret, and an offline backup in your password manager.

| Secret | What | If lost |
|---|---|---|
| `TAURI_SIGNING_PRIVATE_KEY`, `…_PASSWORD` | updater key (minisign) | installed apps can no longer update; users must reinstall once |
| `APPLE_CERTIFICATE`, `…_PASSWORD` | Developer ID Application certificate, `.p12`, base64 | revoke and re-issue in the Apple Developer account |
| `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID` | notarisation (app-specific password, not the account password) | create a new app-specific password |
| `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` | Azure Trusted Signing service principal | rotate the client secret in Azure |

The updater key matters most: its public half is compiled into every installed
copy, so it can't be replaced without users reinstalling. Back it up.

### Updater key (do once)

```bash
npx tauri signer generate -w ~/.tauri/sfs-updater.key   # asks for a password
```

Put the contents of `~/.tauri/sfs-updater.key.pub` in `tauri.conf.json` →
`plugins.updater.pubkey` (public, safe to commit), and the private key file's
contents and password in the two `TAURI_SIGNING_…` secrets. CI refuses to build
signed updates while the placeholder public key is still there.

### macOS: Developer ID and notarisation

Needs the Apple Developer Program (99 USD/year). Create a *Developer ID
Application* certificate, export it with its key as `.p12`, and store
`base64 -i cert.p12` as `APPLE_CERTIFICATE`. CI then signs every binary in the
backend with the hardened runtime (`sidecar/entitlements.plist`: JIT for
wasmtime, unsigned executable memory, no library validation), signs and
notarises the app with Tauri, and checks the result with `codesign --verify`
and `spctl`. Not yet tested: first run needs the certificate.

### Windows: options

Unsigned installers work, but SmartScreen shows "Windows protected your PC"
until a file builds reputation, and PyInstaller executables are a common
antivirus false positive. Signing helps with both. Options, as of late 2026
(check eligibility and prices before choosing):

| | Cost | Notes |
|---|---|---|
| **Azure Trusted Signing** | about 10 USD/month | Microsoft-run; no hardware token; the certificate is renewed automatically; reputation builds per publisher. Identity validation has country and organisation-age requirements. **Wired into CI.** |
| **SignPath Foundation** | free for open-source projects | Signs builds made in public CI from a public repository; approval per project. AGPL SFS should qualify. Needs their GitHub action in place of the Azure step. |
| OV certificate from a CA | about 200–400 USD/year | Since 2023 the key must be on a hardware token or a cloud HSM, which makes CI signing awkward and adds cost. EV no longer skips the SmartScreen warning. |

Recommendation: Azure Trusted Signing if Sidewinder Labs passes its identity
validation, otherwise apply to SignPath Foundation. To enable Trusted Signing,
create an account and a certificate profile, a service principal with the
*Trusted Signing Certificate Profile Signer* role, then set the three `AZURE_…`
secrets and the variables `AZURE_SIGNING_ENDPOINT` (e.g.
`https://weu.codesigning.azure.net`), `AZURE_SIGNING_ACCOUNT` and
`AZURE_SIGNING_PROFILE`. CI signs the backend executable, the app and both
installers (`trusted-signing-cli`). Not yet tested: needs the account.

