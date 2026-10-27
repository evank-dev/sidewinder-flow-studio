// Explore → flow (Create node) and drill-through (settings + panel).
import { useEffect, useState } from 'react'
import { ArrowLeft, Check, Plus, Settings2, Trash2, X } from 'lucide-react'
import { useStore, waitForCanvasNode } from '@/store'
import { api } from '@/utils/api'
import type { ExploreDrillConfig, ExploreField, ExploreSource } from '@/types'
import { isLive } from './source'

const apiError = (e: unknown) => {
  const msg = String(e).replace(/^Error: API \d+: /, '')
  try { return JSON.parse(msg).detail ?? msg } catch { return msg }
}
const fmtCell = (v: unknown): string =>
  v == null ? '∅' : typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 4 })
    : Array.isArray(v) ? `[${v.map(fmtCell).join(', ')}]` : String(v)

function Modal({ title, onClose, children, width = 'w-[540px]' }: {
  title: string; onClose: () => void; children: React.ReactNode; width?: string
}) {
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onMouseDown={onClose}>
      <div className={`${width} max-w-full max-h-[90vh] overflow-y-auto bg-surface-raised border border-canvas-border rounded-xl shadow-node`}
        onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="flex items-center px-4 py-3 border-b border-canvas-border">
          <span className="text-sm font-semibold text-slate-200">{title}</span>
          <button className="btn-ghost px-1.5 ml-auto" onClick={onClose} title="Close"><X size={13} /></button>
        </div>
        <div className="p-4 space-y-4">{children}</div>
      </div>
    </div>
  )
}

function Choice<T extends string>({ value, options, onChange }: {
  value: T; options: { value: T; label: string; hint: string }[]; onChange: (v: T) => void
}) {
  return (
    <div className="grid gap-2">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          className={`text-left px-3 py-2 rounded-lg border transition-colors
            ${value === o.value ? 'border-accent bg-accent/10' : 'border-canvas-border hover:border-subtle'}`}>
          <div className={`text-xs font-semibold ${value === o.value ? 'text-accent' : 'text-slate-300'}`}>{o.label}</div>
          <div className="text-[11px] text-muted mt-0.5">{o.hint}</div>
        </button>
      ))}
    </div>
  )
}

// ── Create node ───────────────────────────────────────────────────────────────

export function CreateNodeDialog({ source, payload, onClose }: {
  source: ExploreSource; payload: () => object | null; onClose: () => void
}) {
  const { activeProject, activeFlowId, addNodeToCanvas, saveProject, setSelectedNode, closeExplore } = useStore()
  const flow = activeProject?.flows.find((f) => f.id === activeFlowId)
  const live = isLive(source)
  const [mode, setMode] = useState<'dataset' | 'chart'>('dataset')
  const [engine, setEngine] = useState<'sql' | 'pandas'>('pandas')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<{ id: string; label: string; notes: string[] } | null>(null)

  const create = async () => {
    const p = payload()
    if (!p || !flow || !activeFlowId) return
    setBusy(true); setError(null)
    try {
      const { node, notes } = await api.explore.node(source, p, mode, live ? engine : undefined)
      // Unconnected, to the right of what is already on the canvas.
      const nodes = (flow.nodes as any[]) ?? []
      const x = nodes.length ? Math.max(...nodes.map((n) => n.position?.x ?? 0)) + 340 : 80
      const y = nodes.length ? Math.min(...nodes.map((n) => n.position?.y ?? 0)) : 200
      const id = crypto.randomUUID()
      addNodeToCanvas(activeFlowId, { id, type: 'processor', position: { x, y }, data: node })
      await waitForCanvasNode(id)
      await saveProject()
      setDone({ id, label: node.label, notes })
    } catch (e) {
      setError(apiError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Create a flow node from this view" onClose={onClose}>
      {done ? (
        <>
          <div className="flex items-start gap-2 text-sm text-slate-200">
            <Check size={16} className="text-status-ok mt-0.5 shrink-0" />
            <span>Added <b>{done.label}</b> to {activeProject?.name} › {flow?.name}, unconnected and saved. Wire it in the flow editor.</span>
          </div>
          {done.notes.map((n) => <div key={n} className="text-xs text-amber-300">{n}</div>)}
          <div className="flex gap-2">
            <button className="btn-pri" onClick={() => { setSelectedNode(done.id); closeExplore() }}>Go to the node</button>
            <button className="btn-ghost border border-canvas-border" onClick={onClose}>Stay in Explore</button>
          </div>
        </>
      ) : (
        <>
          <div>
            <div className="label">What the node returns</div>
            <Choice value={mode} onChange={setMode} options={[
              { value: 'dataset', label: 'The data, with this chart’s filters',
                hint: 'Every column of the source, filtered like the chart. The flow does its own shaping.' },
              { value: 'chart', label: 'This chart’s result',
                hint: 'The aggregated rows the chart shows: its grouping, measures and filters.' },
            ]} />
          </div>
          {live ? (
            <div>
              <div className="label">Engine</div>
              <Choice value={engine} onChange={setEngine} options={[
                { value: 'pandas', label: 'pandas — read into SFS',
                  hint: `Runs the query on ${source.connection} and brings the result into the flow. Free.` },
                { value: 'sql', label: 'SQL ⚡ — push down to the warehouse',
                  hint: `Runs inside ${source.connection}; only the result comes back. Enterprise engine.` },
              ]} />
            </div>
          ) : (
            <div className="text-xs text-muted">
              Creates a <b className="text-slate-300">DuckDB</b> processor. Connect the source node to it — its output arrives as table <code>df</code>.
            </div>
          )}
          {!flow && <div className="text-xs text-amber-300">Open a project and a flow first — the node is added to the flow you have open.</div>}
          {error && <div className="text-xs text-red-400 break-words">{error}</div>}
          <div className="flex items-center gap-2">
            <button className="btn-pri gap-1.5" onClick={create} disabled={!flow || busy}>
              <Plus size={12} /> {busy ? 'Adding…' : flow ? `Add to ${flow.name}` : 'Add node'}
            </button>
            <button className="btn-ghost border border-canvas-border" onClick={onClose}>Cancel</button>
          </div>
        </>
      )}
    </Modal>
  )
}

// ── Drill-through settings ────────────────────────────────────────────────────

export function DrillSettingsDialog({ source, fields, initial, onClose, onSaved }: {
  source: ExploreSource; fields: ExploreField[]; initial: ExploreDrillConfig | null
  onClose: () => void; onSaved: (c: ExploreDrillConfig | null) => void
}) {
  const [connections, setConnections] = useState<{ name: string; dialect: string }[]>([])
  const [connection, setConnection] = useState(initial?.connection ?? '')
  const [tables, setTables] = useState<string[]>([])
  const [table, setTable] = useState(initial?.table ?? '')
  const [columns, setColumns] = useState<string[]>([])
  const [keys, setKeys] = useState(initial?.keys?.length ? initial.keys : [{ field: '', column: '' }])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { api.explore.sources().then((d) => setConnections(d.connections)).catch((e) => setError(apiError(e))) }, [])
  useEffect(() => {
    setTables([]); if (!connection) return
    api.explore.tables(connection).then((d) => setTables(d.tables.map((t) => `${t.schema}.${t.name}`)))
      .catch((e) => setError(apiError(e)))
  }, [connection])
  useEffect(() => {
    setColumns([]); if (!connection || !table) return
    api.explore.schema({ kind: 'table', connection, table }).then((d) => {
      const cols = d.fields.map((f) => f.fid)
      setColumns(cols)
      // Same-named text and date columns are the usual keys: suggest them on a
      // fresh setup. Numeric measures rarely identify rows, so they are left out.
      if (!initial && keys.every((k) => !k.field)) {
        const same = fields.filter((f) => f.semanticType !== 'quantitative' && cols.includes(f.fid))
          .map((f) => ({ field: f.fid, column: f.fid }))
        if (same.length) setKeys(same)
      }
    }).catch((e) => setError(apiError(e)))
  }, [connection, table])

  const save = async (config: ExploreDrillConfig | null) => {
    setError(null)
    try {
      const r = await api.explore.saveDrillConfig(source, config)
      onSaved(r.config); onClose()
    } catch (e) { setError(apiError(e)) }
  }
  const setKey = (i: number, patch: Partial<{ field: string; column: string }>) =>
    setKeys((ks) => ks.map((k, j) => (j === i ? { ...k, ...patch } : k)))

  return (
    <Modal title="Drill-through settings" onClose={onClose} width="w-[620px]">
      <div className="text-xs text-muted">
        Choose the live table that holds the detail behind this data, and which fields identify a row in it.
        Drilling on a chart point then fetches the matching detail rows.
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <div className="label">Connection</div>
          <select className="input text-xs w-full" value={connection} onChange={(e) => { setConnection(e.target.value); setTable('') }}>
            <option value="">— pick —</option>
            {connections.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.dialect})</option>)}
          </select>
        </div>
        <div>
          <div className="label">Detail table</div>
          <select className="input text-xs w-full" value={table} onChange={(e) => setTable(e.target.value)} disabled={!tables.length}>
            <option value="">— pick —</option>
            {tables.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </div>
      <div>
        <div className="label">Keys: field here → column in the detail table</div>
        <div className="space-y-1.5">
          {keys.map((k, i) => (
            <div key={i} className="flex items-center gap-2">
              <select className="input text-xs flex-1" value={k.field} onChange={(e) => setKey(i, { field: e.target.value })}>
                <option value="">— field —</option>
                {fields.map((f) => <option key={f.fid} value={f.fid}>{f.name}</option>)}
              </select>
              <span className="text-muted text-xs">→</span>
              <select className="input text-xs flex-1" value={k.column} onChange={(e) => setKey(i, { column: e.target.value })}
                disabled={!columns.length}>
                <option value="">— column —</option>
                {columns.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <button className="btn-ghost px-1.5" title="Remove key" onClick={() => setKeys((ks) => ks.filter((_, j) => j !== i))}>
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          <button className="btn-ghost text-xs gap-1" onClick={() => setKeys((ks) => [...ks, { field: '', column: '' }])}>
            <Plus size={11} /> Add key
          </button>
        </div>
      </div>
      {error && <div className="text-xs text-red-400 break-words">{error}</div>}
      <div className="flex items-center gap-2">
        <button className="btn-pri" onClick={() => save({ connection, table, keys })} disabled={!connection || !table}>Save</button>
        <button className="btn-ghost border border-canvas-border" onClick={onClose}>Cancel</button>
        {initial && (
          <button className="btn-ghost text-xs text-red-400 ml-auto" onClick={() => save(null)}>Remove drill-through</button>
        )}
      </div>
    </Modal>
  )
}

// ── Drill panel ───────────────────────────────────────────────────────────────

type Detail = Awaited<ReturnType<typeof api.explore.drill>>

export function DrillPanel({ source, config, payload, fieldName, onSettings, onExploreRows, onClose }: {
  source: ExploreSource; config: ExploreDrillConfig | null; payload: () => object | null
  fieldName: (fid: string) => string; onSettings: () => void
  onExploreRows: (connection: string, sql: string) => void; onClose: () => void
}) {
  const [points, setPoints] = useState<Record<string, unknown>[] | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [chartPayload, setChartPayload] = useState<object | null>(null)

  const loadPoints = () => {
    const p = payload()
    setError(null); setDetail(null); setChartPayload(p)
    if (!p) { setPoints([]); return }
    api.explore.query(source, p).then((d) => setPoints(d.rows)).catch((e) => setError(apiError(e)))
  }
  useEffect(loadPoints, [])

  const drillOn = async (row: Record<string, unknown>) => {
    if (!chartPayload) return
    setBusy(true); setError(null)
    try { setDetail(await api.explore.drill(source, chartPayload, row)) }
    catch (e) { setError(apiError(e)) }
    finally { setBusy(false) }
  }

  const cols = (rows: Record<string, unknown>[]) => (rows.length ? Object.keys(rows[0]) : [])

  return (
    <div className="w-[440px] shrink-0 border-l border-canvas-border bg-surface flex flex-col min-h-0" data-testid="drill-panel">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-canvas-border">
        {detail && <button className="btn-ghost px-1.5" onClick={() => setDetail(null)} title="Back to the chart's points"><ArrowLeft size={12} /></button>}
        <span className="text-xs font-semibold text-slate-200">{detail ? 'Detail rows' : 'Drill to detail'}</span>
        <button className="btn-ghost px-1.5 ml-auto" onClick={onSettings} title="Drill-through settings"><Settings2 size={12} /></button>
        <button className="btn-ghost px-1.5" onClick={onClose} title="Close"><X size={12} /></button>
      </div>
      {!config ? (
        <div className="p-4 space-y-3 text-xs text-muted">
          <div>No detail table is set for this data yet.</div>
          <button className="btn-pri" onClick={onSettings}>Set up drill-through</button>
        </div>
      ) : detail ? (
        <div className="flex flex-col min-h-0 flex-1">
          <div className="px-3 py-2 text-[11px] text-muted space-y-1 border-b border-canvas-border">
            <div><span className="text-slate-300">{detail.rows.length.toLocaleString()}{detail.truncated ? '+' : ''} rows</span> from {detail.connection} · {config.table}</div>
            <div>Matched on: {detail.applied.join(', ')}</div>
            {detail.unmapped.length > 0 && (
              <div className="text-amber-300">Not applied (no key column): {detail.unmapped.map(fieldName).join(', ')}</div>
            )}
            <button className="btn-ghost text-xs border border-canvas-border mt-1" onClick={() => onExploreRows(detail.connection, detail.sql)}>
              Explore these rows
            </button>
          </div>
          <div className="flex-1 overflow-auto min-h-0">
            <table className="text-[11px] font-mono w-max min-w-full" data-testid="drill-rows">
              <thead className="sticky top-0 bg-surface-raised">
                <tr>{cols(detail.rows).map((c) => <th key={c} className="text-left px-2 py-1 text-muted font-normal">{c}</th>)}</tr>
              </thead>
              <tbody>
                {detail.rows.map((r, i) => (
                  <tr key={i} className="border-t border-canvas-border/50">
                    {cols(detail.rows).map((c) => <td key={c} className="px-2 py-0.5 text-slate-300 whitespace-nowrap">{fmtCell(r[c])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="flex flex-col min-h-0 flex-1">
          <div className="px-3 py-2 text-[11px] text-muted border-b border-canvas-border flex items-center">
            <span>Pick a point of the chart to fetch its rows from {config.connection} · {config.table}</span>
            <button className="btn-ghost text-[11px] ml-auto" onClick={loadPoints} title="Re-read the chart">Refresh</button>
          </div>
          {busy && <div className="px-3 py-2 text-xs text-muted">Fetching detail…</div>}
          {error && <div className="px-3 py-2 text-xs text-red-400 break-words">{error}</div>}
          {points && points.length === 0 && !error && (
            <div className="px-3 py-2 text-xs text-muted">Build a chart first — its points are listed here.</div>
          )}
          <div className="flex-1 overflow-y-auto min-h-0">
            {points?.slice(0, 300).map((r, i) => (
              <button key={i} onClick={() => drillOn(r)} disabled={busy} data-testid="drill-point"
                className="w-full text-left px-3 py-1.5 border-b border-canvas-border/40 hover:bg-surface-overlay text-xs">
                {Object.entries(r).map(([k, v]) => (
                  <span key={k} className="mr-3 whitespace-nowrap">
                    <span className="text-muted">{fieldName(k)}</span> <span className="text-slate-200">{fmtCell(v)}</span>
                  </span>
                ))}
              </button>
            ))}
            {points && points.length > 300 && <div className="px-3 py-2 text-[11px] text-muted">First 300 points shown</div>}
          </div>
        </div>
      )}
    </div>
  )
}
