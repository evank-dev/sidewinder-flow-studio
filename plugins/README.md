# Plugins

Engine plugins for SFS. Each subfolder is a standalone installable Python
package that registers one or more execution engines through the
[plugin contract](../docs/PLUGINS.md) — no SFS code changes required.

| Plugin | Engine | Status |
|---|---|---|
| [sfs-plugin-sklearn](sfs-plugin-sklearn) | `scikit-learn` (in-process) and `scikit-learn (isolated)` | reference implementation |

## Installing

```bash
pip install -e plugins/sfs-plugin-sklearn
```

Restart SFS; the engine appears in the node picker with a 🧩 badge. The UI
renders from `GET /api/capabilities`, so no frontend change is needed.

## Writing your own

Copy `sfs-plugin-sklearn` — it's a complete working example of the contract
(entry point, `register(api)`, `EngineSpec`, `run(EngineContext)`, declared
parameters, lazy dependency imports). See [docs/PLUGINS.md](../docs/PLUGINS.md).

## In-process vs isolated

Plugins here run **in-process**: their dependencies install into SFS's own
environment. That is fine for libraries that coexist with the core stack
(scikit-learn does).

Libraries with aggressive version pins — PyCaret is the usual offender — should
use the **isolated runtime** instead: the library lives in its own virtual
environment and frames cross as Arrow files, leaving the core environment
untouched. The registration contract is the same; only the engine's `run`
differs (it calls `api.run_isolated(...)`).

`sfs-plugin-sklearn` ships both variants so you can compare them:

| Engine | Where it runs |
|---|---|
| `sklearn` | in-process, shares SFS's environment |
| `sklearn_isolated` | separate venv via `runner.py`, Arrow handoff |

Set up an environment once:

```bash
export SFS_PLUGIN_VENVS_DIR=./plugin_venvs
python -m venv $SFS_PLUGIN_VENVS_DIR/sklearn
$SFS_PLUGIN_VENVS_DIR/sklearn/bin/pip install pyarrow pandas scikit-learn
```
