// Explore — Graphic Walker in server-side computation mode over SFS sources.
// Charts are compiled to SQL by the backend (/api/explore/query) and run where
// the data lives; only the small result reaches the browser.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GraphicWalker, slateTheme } from '@kanaries/graphic-walker'
import type { IDataQueryPayload, IMutField, IRow, IUIThemeConfig, VizSpecStore } from '@kanaries/graphic-walker'
import Editor from '@monaco-editor/react'
import {
  ArrowLeft, Calendar, ChevronDown, ChevronRight, Code2, Database, Hash, Layers, Play, RefreshCw, Search, Server, Type,
} from 'lucide-react'
import { useStore } from '@/store'
import { api } from '@/utils/api'
import type { ExploreField, ExploreFrame, ExplorePersisted, ExploreSource, ExploreTable } from '@/types'
import { isLive, sourceKey } from './source'

interface QueryLog {
  sql: string
  rows: number
  compile_ms: number
  exec_ms: number
  total_ms: number
  truncated: boolean
  row_cap?: number
  dialect?: string
  error?: string
}

// Test hook: browser checks drive Graphic Walker through its store.
declare global {
  interface Window {
    __sfsExplore?: { store: VizSpecStore | null; log: QueryLog[]; payloads: IDataQueryPayload[] }
  }
}

// SFS palette (tailwind.config.js) mapped onto Graphic Walker's UI tokens.
const SFS_THEME: IUIThemeConfig = {
  light: slateTheme.light,
  dark: {
    background: '#090c14', foreground: '#e2e8f0',
    card: '#111827', 'card-foreground': '#e2e8f0',
    popover: '#1a2235', 'popover-foreground': '#e2e8f0',
    primary: '#38bdf8', 'primary-foreground': '#090c14',
    muted: '#1a2235', 'muted-foreground': '#94a3b8',
    secondary: '#212d45', 'secondary-foreground': '#e2e8f0',
    accent: '#212d45', 'accent-foreground': '#e2e8f0',
    destructive: '#f87171', 'destructive-foreground': '#090c14',
    dimension: '#38bdf8', measure: '#34d399',
    border: '#1e2540', input: '#1e2540', ring: '#38bdf8',
  },
}

// Database timestamps are almost always stored without a zone. Graphic Walker
// otherwise shifts date buckets by the browser's UTC offset (a "day" starting
// at 02:00 in Athens). Still adjustable per chart in its config panel.
const GW_DEFAULTS = { config: { timezoneDisplayOffset: 0 } }

const fmt = (n?: number | null) => (n == null ? '' : n.toLocaleString())
const apiError = (e: unknown) => {
  const msg = String(e).replace(/^Error: API \d+: /, '')
  try { return JSON.parse(msg).detail ?? msg } catch { return msg }
}

const typeIcon = (f: ExploreField) =>
  f.semanticType === 'temporal' ? <Calendar size={11} className="text-amber-300 shrink-0" />
    : f.semanticType === 'quantitative' ? <Hash size={11} className="text-status-ok shrink-0" />
      : <Type size={11} className="text-accent shrink-0" />

// ── Source picker ─────────────────────────────────────────────────────────────

function SourceItem({ active, label, sub, detail, onClick }: {
  active: boolean; label: string; sub: string; detail?: string; onClick: () => void
}) {
  return (
    <button onClick={onClick} title={detail ? `${label}\n${detail}` : label}
      ref={active ? (el) => el?.scrollIntoView({ block: 'nearest' }) : undefined}
      className={`w-full text-left px-3 py-1.5 rounded-md text-xs flex flex-col gap-0.5 transition-colors
        ${active ? 'bg-accent/15 text-accent' : 'text-slate-300 hover:bg-surface-overlay'}`}>
      <span className="truncate">{label}</span>
      <span className="text-[10px] text-muted truncate">{sub}</span>
      {detail && <span className="text-[10px] text-muted/70 font-mono truncate">{detail}</span>}
    </button>
  )
}

/** One live connection: its tables load when it is first expanded. */
function ConnectionTree({ name, dialect, q, active, onPick, onSql }: {
  name: string; dialect: string; q: string; active: string | null
  onPick: (s: ExploreSource) => void; onSql: (connection: string) => void
}) {
  const mine = !!active && (active.startsWith(`table:${name}:`) || active.startsWith(`sql:${name}:`))
  const [open, setOpen] = useState(mine)
  const [tables, setTables] = useState<ExploreTable[] | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { if (mine) setOpen(true) }, [mine])
  useEffect(() => {
    if (!open || tables || error) return
    api.explore.tables(name)
      .then((d) => { setTables(d.tables); setTruncated(d.truncated) })
      .catch((e) => setError(apiError(e)))
  }, [open, tables, error, name])

  const shown = (tables ?? []).filter((t) => !q || `${t.schema}.${t.name}`.toLowerCase().includes(q))
  if (q && tables && !shown.length && !name.toLowerCase().includes(q)) return null

  return (
    <div>
      <button className="w-full flex items-center gap-1.5 px-2 py-1 rounded-md text-xs text-slate-300 hover:bg-surface-overlay"
        onClick={() => setOpen((o) => !o)} title={`${name} (${dialect})`}>
        {open ? <ChevronDown size={11} className="text-muted" /> : <ChevronRight size={11} className="text-muted" />}
        <Server size={11} className="text-amber-300 shrink-0" />
        <span className="truncate">{name}</span>
        <span className="ml-auto text-[10px] text-muted">{dialect}</span>
      </button>
      {open && (
        <div className="ml-3 pl-1 border-l border-canvas-border flex flex-col gap-0.5">
          <button className="flex items-center gap-1.5 px-3 py-1 text-xs text-accent hover:bg-surface-overlay rounded-md"
            onClick={() => onSql(name)}>
            <Code2 size={11} /> SQL query…
          </button>
          {!tables && !error && <div className="px-3 py-1 text-[11px] text-muted">Loading tables…</div>}
          {error && <div className="px-3 py-1 text-[11px] text-red-400 break-words">{error}</div>}
          {tables && tables.length === 0 && <div className="px-3 py-1 text-[11px] text-muted">No tables visible to this login</div>}
          {shown.map((t) => {
            const table = `${t.schema}.${t.name}`
            return (
              <SourceItem key={table} active={active === `table:${name}:${table}`} label={table}
                sub={`${t.kind}${t.rows != null ? ` · ≈${fmt(t.rows)} rows` : ''}`}
                onClick={() => onPick({ kind: 'table', connection: name, table })} />
            )
          })}
          {truncated && <div className="px-3 py-1 text-[10px] text-muted">First 2,000 tables shown — type to filter</div>}
        </div>
      )}
    </div>
  )
}

function SourcePicker({ current, onPick, onSql }: {
  current: ExploreSource | null; onPick: (s: ExploreSource) => void; onSql: (connection: string) => void
}) {
  const [frames, setFrames] = useState<ExploreFrame[]>([])
  const [persisted, setPersisted] = useState<ExplorePersisted[]>([])
  const [connections, setConnections] = useState<{ name: string; dialect: string }[]>([])
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [reload, setReload] = useState(0)

  const load = useCallback(() => {
    setLoading(true)
    api.explore.sources()
      .then((d) => { setFrames(d.frames); setPersisted(d.persisted); setConnections(d.connections); setError(null) })
      .catch((e) => setError(apiError(e)))
      .finally(() => setLoading(false))
    setReload((n) => n + 1)
  }, [])
  useEffect(load, [load])

  const q = filter.trim().toLowerCase()
  const match = (...parts: (string | null | undefined)[]) => !q || parts.some((p) => p?.toLowerCase().includes(q))

  // project › flow → frames
  const groups = useMemo(() => {
    const g = new Map<string, ExploreFrame[]>()
    for (const f of frames) {
      if (!match(f.label, f.project, f.flow)) continue
      const k = `${f.project} › ${f.flow}`
      g.set(k, [...(g.get(k) ?? []), f])
    }
    return [...g.entries()]
  }, [frames, q])
  const persistedShown = persisted.filter((p) => match(p.table, p.node))
  const active = current ? sourceKey(current) : null

  const section = (id: string, title: string, icon: JSX.Element, body: JSX.Element[] | JSX.Element) => (
    <div key={id} className="mb-2">
      <button className="w-full flex items-center gap-1.5 px-2 py-1 text-[10px] uppercase tracking-wide text-muted hover:text-slate-300"
        onClick={() => setCollapsed((c) => ({ ...c, [id]: !c[id] }))}>
        {collapsed[id] ? <ChevronRight size={11} /> : <ChevronDown size={11} />}{icon}
        <span className="truncate">{title}</span>
      </button>
      {!collapsed[id] && <div className="flex flex-col gap-0.5">{body}</div>}
    </div>
  )

  return (
    <div className="flex flex-col min-h-0 flex-1">
      <div className="flex items-center gap-1 p-2">
        <div className="relative flex-1">
          <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
          <input className="input w-full text-xs py-1 pl-6" placeholder="Filter sources…"
            value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <button className="btn-ghost px-1.5" onClick={load} title="Refresh sources">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-1 pb-2">
        {error && <div className="px-3 py-2 text-xs text-red-400 break-words">{error}</div>}
        {groups.map(([g, fs]) => section(g, g, <Layers size={11} />, fs.map((f) => (
          <SourceItem key={f.node_id} active={active === `frame:${f.project_id}:${f.node_id}`} label={f.label}
            sub={`${fmt(f.rows)} rows · ${f.columns} cols`}
            detail={f.column_names.join(', ') + (f.columns > f.column_names.length ? ', …' : '')}
            onClick={() => onPick({ kind: 'frame', project_id: f.project_id, node_id: f.node_id })} />
        ))))}
        {persistedShown.length > 0 && section('__persist', 'Persisted', <Database size={11} />, persistedShown.map((p) => (
          <SourceItem key={p.table} active={active === `persist:${p.table}`} label={p.table}
            sub={`${fmt(p.rows)} rows · ${p.columns} cols${p.node ? ` · ${p.node}` : ''}`}
            onClick={() => onPick({ kind: 'persist', table: p.table })} />
        )))}
        {connections.length > 0 && section('__live', 'Databases — live', <Server size={11} />, connections.map((c) => (
          <ConnectionTree key={`${c.name}:${reload}`} name={c.name} dialect={c.dialect} q={q} active={active}
            onPick={onPick} onSql={onSql} />
        )))}
        {!loading && !error && !frames.length && !persisted.length && !connections.length && (
          <div className="px-3 py-2 text-xs text-muted">
            Nothing to explore yet. Run a flow, or add a connection, and it appears here.
          </div>
        )}
      </div>
    </div>
  )
}

// ── Schema browser ────────────────────────────────────────────────────────────

function SchemaList({ fields, rows, approx }: { fields: ExploreField[]; rows?: number | null; approx: boolean }) {
  return (
    <div className="border-t border-canvas-border flex flex-col min-h-0 max-h-[45%]">
      <div className="px-3 py-1.5 text-[10px] uppercase tracking-wide text-muted flex justify-between">
        <span>Schema · {fields.length} columns</span>
        {rows != null && <span className="normal-case tracking-normal">{approx ? '≈' : ''}{fmt(rows)} rows</span>}
      </div>
      <div className="overflow-y-auto px-2 pb-2" data-testid="schema">
        {fields.map((f) => (
          <div key={f.fid} className="flex items-center gap-1.5 px-1 py-0.5 text-xs" title={`${f.name} · ${f.sqlType}`}>
            {typeIcon(f)}
            <span className="truncate flex-1 text-slate-300">{f.name}</span>
            <span className="text-[10px] text-muted font-mono truncate max-w-[45%]">{f.sqlType}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── SQL source editor ─────────────────────────────────────────────────────────

function SqlEditor({ connection, initial, onRun, onCancel }: {
  connection: string; initial: string; onRun: (sql: string) => void; onCancel: () => void
}) {
  const [sql, setSql] = useState(initial)
  // Read the text from the editor itself when running: Ctrl+Enter straight
  // after typing fires before React has re-rendered with the last keystrokes.
  const editor = useRef<{ getValue: () => string } | null>(null)
  const run = useRef(() => {})
  run.current = () => {
    const text = editor.current?.getValue() ?? sql
    if (text.trim()) onRun(text)
  }

  return (
    <div className="flex-1 flex flex-col gap-3 p-6 min-h-0 overflow-y-auto">
      <div>
        <div className="text-sm font-semibold text-slate-200">SQL query on <span className="text-accent">{connection}</span></div>
        <div className="text-xs text-muted mt-1 max-w-2xl">
          One SELECT, in this database's own SQL. It becomes the data behind the chart, and runs on the
          database each time the chart changes — read-only credentials are recommended for exploration.
        </div>
      </div>
      <div className="relative h-72 shrink-0 rounded-lg overflow-hidden border border-canvas-border"
        onKeyDown={(e) => e.stopPropagation()} data-testid="sql-editor">
        <div className="absolute inset-0">
          <Editor height="100%" defaultLanguage="sql" theme="vs-dark" value={sql}
            onChange={(v) => setSql(v ?? '')}
            onMount={(ed, monaco) => {
              editor.current = ed
              ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => run.current())
              ed.focus()
            }}
            options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, wordWrap: 'on',
                       automaticLayout: true, padding: { top: 8 } }} />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button className="btn-pri gap-1.5" onClick={() => run.current()} disabled={!sql.trim()}>
          <Play size={12} /> Explore
        </button>
        <button className="btn-ghost border border-canvas-border" onClick={onCancel}>Cancel</button>
        <span className="text-[11px] text-muted">Ctrl+Enter to run</span>
      </div>
    </div>
  )
}

// ── Canvas + Show SQL ─────────────────────────────────────────────────────────

function Walker({ source, fields, onEditSql }: { source: ExploreSource; fields: ExploreField[]; onEditSql: () => void }) {
  const [log, setLog] = useState<QueryLog[]>([])
  const [showSql, setShowSql] = useState(false)
  const storeRef = useRef<VizSpecStore | null>(null)

  useEffect(() => {
    window.__sfsExplore = { store: null, log: [], payloads: [] }
    const id = setInterval(() => { if (window.__sfsExplore) window.__sfsExplore.store = storeRef.current }, 200)
    return () => clearInterval(id)
  }, [source])

  const record = (e: QueryLog) => {
    window.__sfsExplore?.log.push(e)
    setLog((l) => [e, ...l].slice(0, 50))
  }

  // Must be referentially stable: Graphic Walker re-runs every query when the
  // computation prop changes, and each result re-renders this component — an
  // inline function here loops forever (hundreds of identical queries per chart).
  const computation = useCallback(async (payload: IDataQueryPayload): Promise<IRow[]> => {
    window.__sfsExplore?.payloads.push(payload)
    const t0 = performance.now()
    try {
      const d = await api.explore.query(source, payload)
      record({ sql: d.sql, rows: d.rows.length, compile_ms: d.compile_ms, exec_ms: d.exec_ms, dialect: d.dialect,
               total_ms: Math.round(performance.now() - t0), truncated: d.truncated, row_cap: d.row_cap })
      return d.rows as IRow[]
    } catch (e) {
      const detail = apiError(e)
      record({ sql: JSON.stringify(payload), rows: 0, compile_ms: 0, exec_ms: 0,
               total_ms: Math.round(performance.now() - t0), truncated: false, error: detail })
      throw new Error(detail)
    }
  }, [source])

  const last = log[0]
  const dialect = log.find((q) => q.dialect)?.dialect
  return (
    <div className="flex flex-col flex-1 min-w-0 min-h-0">
      {isLive(source) && (
        <div className="px-4 py-1.5 text-xs border-b border-canvas-border bg-surface flex items-center gap-2 shrink-0"
          data-testid="live-bar">
          <Server size={12} className="text-amber-300" />
          <span className="text-slate-300">
            Live on <span className="text-amber-200">{source.connection}</span>{dialect ? ` · ${dialect}` : ''}
            {source.kind === 'table' ? ` · ${source.table}` : ' · SQL query'}
          </span>
          <span className="text-muted hidden lg:inline">— each chart change runs a query on this database</span>
          {source.kind === 'sql' && (
            <button className="btn-ghost text-xs py-0.5 ml-auto gap-1" onClick={onEditSql}><Code2 size={11} /> Edit SQL</button>
          )}
        </div>
      )}
      {last?.truncated && (
        <div className="px-4 py-1.5 text-xs bg-amber-950/60 border-b border-amber-500/30 text-amber-200 shrink-0" role="status">
          Showing the first {fmt(last.row_cap)} rows of this view — add a filter or aggregate to see all of it.
        </div>
      )}
      <div className="flex-1 overflow-auto min-h-0">
        <GraphicWalker
          fields={fields as unknown as IMutField[]}
          computation={computation}
          storeRef={storeRef}
          appearance="dark"
          uiTheme={SFS_THEME}
          defaultConfig={GW_DEFAULTS}
          computationTimeout={120_000}
          // Drops the "kanaries docs" button, whose logo is fetched from an
          // external CDN — Explore must work offline.
          toolbar={{ exclude: ['kanaries'] }}
        />
      </div>
      <div className="shrink-0 border-t border-canvas-border bg-surface">
        <button className="w-full flex items-center gap-2 px-3 py-1 text-[11px] text-muted hover:text-slate-300"
          onClick={() => setShowSql((v) => !v)} data-testid="sql-toggle">
          <Code2 size={12} />
          <span>{showSql ? 'Hide SQL' : 'Show SQL'}</span>
          {last && (
            <span className={`ml-auto font-mono ${last.error ? 'text-red-400' : ''}`}>
              {last.error ? 'last query failed'
                : `${fmt(last.rows)} rows${last.truncated ? ' (capped)' : ''} · db ${last.exec_ms} ms · round-trip ${last.total_ms} ms`}
            </span>
          )}
        </button>
        {showSql && (
          <div className="h-48 overflow-auto px-3 pb-2 font-mono text-[11px]" data-testid="sql-log">
            {log.length === 0 && <div className="text-muted">No queries yet — drag fields onto the chart.</div>}
            {log.map((q, i) => (
              <div key={i} className={`mb-2 ${q.error ? 'text-red-400' : 'text-slate-300'}`}>
                <div className="text-accent">
                  {q.error ? 'ERROR' : `${fmt(q.rows)} rows${q.truncated ? ' (capped)' : ''}`}{q.dialect ? ` · ${q.dialect}` : ''} · compile {q.compile_ms} ms · db {q.exec_ms} ms · round-trip {q.total_ms} ms
                </div>
                <div className="whitespace-pre-wrap break-all select-text">{q.error ?? q.sql}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── View ──────────────────────────────────────────────────────────────────────

export default function ExploreView() {
  const { exploreSource: source, openExplore, closeExplore } = useStore()
  const [schema, setSchema] = useState<{ fields: ExploreField[]; rows?: number | null } | null>(null)
  const [error, setError] = useState<string | null>(null)
  // A SQL source being written or edited: shown instead of the chart.
  const [draft, setDraft] = useState<{ connection: string; sql: string } | null>(null)

  useEffect(() => {
    // Keep the URL in step with the source so the view can be bookmarked.
    const hash = source ? `#/explore?${new URLSearchParams(source as Record<string, string>)}` : '#/explore'
    if (window.location.hash !== hash) history.replaceState(null, '', hash)
    setSchema(null); setError(null)
    if (!source) return
    let live = true
    api.explore.schema(source)
      .then((d) => live && setSchema(d))
      .catch((e) => live && setError(apiError(e)))
    return () => { live = false }
  }, [source && sourceKey(source)])

  // However Explore is left (back arrow, top-bar button, a flow tab), drop the
  // #/explore hash so a reload opens the flow editor.
  useEffect(() => () => history.replaceState(null, '', window.location.pathname + window.location.search), [])

  const editSql = (connection: string) =>
    setDraft({ connection, sql: source?.kind === 'sql' && source.connection === connection ? source.sql : '' })

  return (
    <div className="flex flex-1 overflow-hidden min-h-0">
      <aside className="w-72 shrink-0 border-r border-canvas-border bg-surface flex flex-col min-h-0">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-canvas-border">
          <button className="btn-ghost px-1.5" onClick={closeExplore} title="Back to flows"><ArrowLeft size={13} /></button>
          <span className="text-sm font-semibold text-slate-200">Explore</span>
        </div>
        <SourcePicker current={source} onPick={(s) => { setDraft(null); openExplore(s) }} onSql={editSql} />
        {schema && !draft && <SchemaList fields={schema.fields} rows={schema.rows} approx={source?.kind === 'table'} />}
      </aside>

      {draft ? (
        <SqlEditor key={draft.connection} connection={draft.connection} initial={draft.sql}
          onCancel={() => setDraft(null)}
          onRun={(sql) => { setDraft(null); openExplore({ kind: 'sql', connection: draft.connection, sql }) }} />
      ) : !source ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center p-8">
          <Layers size={36} className="text-subtle" />
          <div className="text-lg font-semibold text-slate-300">Pick a source to explore</div>
          <div className="text-sm text-muted max-w-sm">
            Node outputs from your flow runs, persisted tables and your database connections are listed
            on the left. Charts run as SQL where the data lives, so large tables stay fast.
          </div>
        </div>
      ) : error ? (
        <div className="flex-1 p-6 flex flex-col gap-3 items-start">
          <div className="text-sm text-red-400 font-mono whitespace-pre-wrap">{error}</div>
          {source.kind === 'sql' && (
            <button className="btn-ghost border border-canvas-border gap-1.5" onClick={() => editSql(source.connection)}>
              <Code2 size={12} /> Edit SQL
            </button>
          )}
        </div>
      ) : !schema ? (
        <div className="flex-1 p-6 text-sm text-muted">{isLive(source) ? 'Reading the table from the database…' : 'Loading schema…'}</div>
      ) : (
        <Walker key={sourceKey(source)} source={source} fields={schema.fields}
          onEditSql={() => isLive(source) && editSql(source.connection)} />
      )}
    </div>
  )
}
