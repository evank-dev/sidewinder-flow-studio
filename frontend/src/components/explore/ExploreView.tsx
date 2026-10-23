// Explore — Graphic Walker in server-side computation mode over SFS sources.
// Charts are compiled to SQL by the backend (/api/explore/query) and run where
// the data lives; only the small result reaches the browser.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GraphicWalker, slateTheme } from '@kanaries/graphic-walker'
import type { IDataQueryPayload, IMutField, IRow, IUIThemeConfig, VizSpecStore } from '@kanaries/graphic-walker'
import { ArrowLeft, Calendar, ChevronDown, ChevronRight, Code2, Database, Hash, Layers, RefreshCw, Search, Type } from 'lucide-react'
import { useStore } from '@/store'
import { api } from '@/utils/api'
import type { ExploreField, ExploreFrame, ExplorePersisted, ExploreSource } from '@/types'
import { sourceKey } from './source'

interface QueryLog {
  sql: string
  rows: number
  compile_ms: number
  exec_ms: number
  total_ms: number
  truncated: boolean
  row_cap?: number
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

const fmt = (n?: number) => (n == null ? '' : n.toLocaleString())

const typeIcon = (f: ExploreField) =>
  f.semanticType === 'temporal' ? <Calendar size={11} className="text-amber-300 shrink-0" />
    : f.semanticType === 'quantitative' ? <Hash size={11} className="text-status-ok shrink-0" />
      : <Type size={11} className="text-accent shrink-0" />

// ── Source picker ─────────────────────────────────────────────────────────────

function SourcePicker({ current, onPick }: { current: ExploreSource | null; onPick: (s: ExploreSource) => void }) {
  const [frames, setFrames] = useState<ExploreFrame[]>([])
  const [persisted, setPersisted] = useState<ExplorePersisted[]>([])
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  const load = useCallback(() => {
    setLoading(true)
    api.explore.sources()
      .then((d) => { setFrames(d.frames); setPersisted(d.persisted); setError(null) })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
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

  const item = (key: string, label: string, sub: string, onClick: () => void, detail?: string) => (
    <button key={key} onClick={onClick} title={detail ? `${label}\n${detail}` : label}
      ref={active === key ? (el) => el?.scrollIntoView({ block: 'nearest' }) : undefined}
      className={`w-full text-left px-3 py-1.5 rounded-md text-xs flex flex-col gap-0.5 transition-colors
        ${active === key ? 'bg-accent/15 text-accent' : 'text-slate-300 hover:bg-surface-overlay'}`}>
      <span className="truncate">{label}</span>
      <span className="text-[10px] text-muted truncate">{sub}</span>
      {detail && <span className="text-[10px] text-muted/70 font-mono truncate">{detail}</span>}
    </button>
  )
  const section = (id: string, title: string, icon: JSX.Element, body: JSX.Element[]) => (
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
        {!loading && !error && frames.length === 0 && persisted.length === 0 && (
          <div className="px-3 py-2 text-xs text-muted">
            Nothing cached yet. Run a flow, then its node outputs appear here.
          </div>
        )}
        {groups.map(([g, fs]) => section(g, g, <Layers size={11} />, fs.map((f) =>
          item(`frame:${f.project_id}:${f.node_id}`, f.label, `${fmt(f.rows)} rows · ${f.columns} cols`,
            () => onPick({ kind: 'frame', project_id: f.project_id, node_id: f.node_id }),
            f.column_names.join(', ') + (f.columns > f.column_names.length ? ', …' : '')))))}
        {persistedShown.length > 0 && section('__persist', 'Persisted', <Database size={11} />, persistedShown.map((p) =>
          item(`persist:${p.table}`, p.table, `${fmt(p.rows)} rows · ${p.columns} cols${p.node ? ` · ${p.node}` : ''}`,
            () => onPick({ kind: 'persist', table: p.table }))))}
      </div>
    </div>
  )
}

// ── Schema browser ────────────────────────────────────────────────────────────

function SchemaList({ fields, rows }: { fields: ExploreField[]; rows?: number }) {
  return (
    <div className="border-t border-canvas-border flex flex-col min-h-0 max-h-[45%]">
      <div className="px-3 py-1.5 text-[10px] uppercase tracking-wide text-muted flex justify-between">
        <span>Schema · {fields.length} columns</span>
        {rows != null && <span className="normal-case tracking-normal">{fmt(rows)} rows</span>}
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

// ── Canvas + Show SQL ─────────────────────────────────────────────────────────

function Walker({ source, fields }: { source: ExploreSource; fields: ExploreField[] }) {
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
      record({ sql: d.sql, rows: d.rows.length, compile_ms: d.compile_ms, exec_ms: d.exec_ms,
               total_ms: Math.round(performance.now() - t0), truncated: d.truncated, row_cap: d.row_cap })
      return d.rows as IRow[]
    } catch (e) {
      const msg = String(e).replace(/^Error: API \d+: /, '')
      let detail = msg
      try { detail = JSON.parse(msg).detail ?? msg } catch { /* plain text */ }
      record({ sql: JSON.stringify(payload), rows: 0, compile_ms: 0, exec_ms: 0,
               total_ms: Math.round(performance.now() - t0), truncated: false, error: detail })
      throw new Error(detail)
    }
  }, [source])

  const last = log[0]
  return (
    <div className="flex flex-col flex-1 min-w-0 min-h-0">
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
                  {q.error ? 'ERROR' : `${fmt(q.rows)} rows${q.truncated ? ' (capped)' : ''}`} · compile {q.compile_ms} ms · db {q.exec_ms} ms · round-trip {q.total_ms} ms
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
  const [schema, setSchema] = useState<{ fields: ExploreField[]; rows?: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Keep the URL in step with the source so the view can be bookmarked.
    const hash = source ? `#/explore?${new URLSearchParams(source as Record<string, string>)}` : '#/explore'
    if (window.location.hash !== hash) history.replaceState(null, '', hash)
    setSchema(null); setError(null)
    if (!source) return
    let live = true
    api.explore.schema(source)
      .then((d) => live && setSchema(d))
      .catch((e) => live && setError(String(e).replace(/^Error: API \d+: /, '')))
    return () => { live = false }
  }, [source && sourceKey(source)])

  // However Explore is left (back arrow, top-bar button, a flow tab), drop the
  // #/explore hash so a reload opens the flow editor.
  useEffect(() => () => history.replaceState(null, '', window.location.pathname + window.location.search), [])

  return (
    <div className="flex flex-1 overflow-hidden min-h-0">
      <aside className="w-72 shrink-0 border-r border-canvas-border bg-surface flex flex-col min-h-0">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-canvas-border">
          <button className="btn-ghost px-1.5" onClick={closeExplore} title="Back to flows"><ArrowLeft size={13} /></button>
          <span className="text-sm font-semibold text-slate-200">Explore</span>
        </div>
        <SourcePicker current={source} onPick={(s) => openExplore(s)} />
        {schema && <SchemaList fields={schema.fields} rows={schema.rows} />}
      </aside>

      {!source ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center p-8">
          <Layers size={36} className="text-subtle" />
          <div className="text-lg font-semibold text-slate-300">Pick a source to explore</div>
          <div className="text-sm text-muted max-w-sm">
            Node outputs from your flow runs and persisted tables are listed on the left.
            Charts run as SQL on the server, so large frames stay fast.
          </div>
        </div>
      ) : error ? (
        <div className="flex-1 p-6 text-sm text-red-400 font-mono whitespace-pre-wrap">{error}</div>
      ) : !schema ? (
        <div className="flex-1 p-6 text-sm text-muted">Loading schema…</div>
      ) : (
        <Walker key={sourceKey(source)} source={source} fields={schema.fields} />
      )}
    </div>
  )
}
