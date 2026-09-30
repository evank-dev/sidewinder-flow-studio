# Plugins

Engine plugins for SFS. Each subfolder is a standalone installable Python
package that registers one or more execution engines through the
[plugin contract](../docs/PLUGINS.md) — no SFS code changes required.

| Plugin | Engine | Status |
|---|---|---|
| [sfs-plugin-sklearn](sfs-plugin-sklearn) | `scikit-learn` — train models on the frame | reference implementation |

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

Libraries with aggressive version pins — PyCaret is the usual offender — will be
served by the planned **isolated runtime**, where the library lives in its own
virtual environment and frames cross as Arrow files, leaving the core
environment untouched. The registration contract is the same; only the engine's
`run` differs.
