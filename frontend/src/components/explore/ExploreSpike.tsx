// Phase 0 spike: Graphic Walker in server-side computation mode.
// Opened via  #/explore?kind=frame&project_id=…&node_id=…
//        or   #/explore?kind=table&connection=…&table=…
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GraphicWalker } from '@kanaries/graphic-walker'
import type { IDataQueryPayload, IMutField, IRow, VizSpecStore } from '@kanaries/graphic-walker'

interface QueryLog {
  sql: string
  rows: number
  compile_ms: number
  exec_ms: number
  total_ms: number
  truncated: boolean
  error?: string
}

declare global {
  interface Window {
    __sfsExplore?: { store: VizSpecStore | null; log: QueryLog[]; payloads: IDataQueryPayload[] }
  }
}

function sourceFromHash(): Record<string, string> {
  const q = window.location.hash.split('?')[1] ?? ''
  return Object.fromEntries(new URLSearchParams(q))
}

export default function ExploreSpike() {
  const source = useMemo(sourceFromHash, [])
  const [fields, setFields] = useState<IMutField[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [log, setLog] = useState<QueryLog[]>([])
  const storeRef = useRef<VizSpecStore | null>(null)
  const dark = document.documentElement.classList.contains('dark') ||
    window.matchMedia('(prefers-color-scheme: dark)').matches

  useEffect(() => {
    window.__sfsExplore = { store: null, log: [], payloads: [] }
    fetch(`/api/explore/schema?${new URLSearchParams(source)}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error(await r.text()))))
      .then((d) => setFields(d.fields))
      .catch((e) => setError(String(e)))
  }, [source])

  useEffect(() => {
    const id = setInterval(() => { if (window.__sfsExplore) window.__sfsExplore.store = storeRef.current }, 200)
    return () => clearInterval(id)
  }, [])

  // Must be referentially stable: Graphic Walker re-runs every query when the
  // computation prop changes, and each result re-renders this component — an
  // inline function here loops forever (hundreds of identical queries per chart).
  const computation = useCallback(async (payload: IDataQueryPayload): Promise<IRow[]> => {
    window.__sfsExplore?.payloads.push(payload)
    const t0 = performance.now()
    const r = await fetch('/api/explore/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, payload }),
    })
    const total_ms = Math.round(performance.now() - t0)
    if (!r.ok) {
      const entry = { sql: JSON.stringify(payload), rows: 0, compile_ms: 0, exec_ms: 0, total_ms, truncated: false, error: await r.text() }
      window.__sfsExplore?.log.push(entry)
      setLog((l) => [entry, ...l].slice(0, 20))
      throw new Error(entry.error)
    }
    const d = await r.json()
    const entry = { sql: d.sql, rows: d.rows.length, compile_ms: d.compile_ms, exec_ms: d.exec_ms, total_ms, truncated: d.truncated }
    window.__sfsExplore?.log.push(entry)
    setLog((l) => [entry, ...l].slice(0, 20))
    return d.rows
  }, [source])

  if (error) return <div className="p-6 text-red-400 font-mono text-sm">{error}</div>
  if (!fields) return <div className="p-6 text-muted text-sm">Loading schema…</div>

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden">
      <div className="flex-1 overflow-auto">
        <GraphicWalker
          fields={fields}
          computation={computation}
          storeRef={storeRef}
          appearance={dark ? 'dark' : 'light'}
          computationTimeout={120_000}
        />
      </div>
      <div className="h-48 shrink-0 overflow-auto border-t border-canvas-border bg-surface p-2 font-mono text-[11px]" data-testid="sql-log">
        <div className="text-muted mb-1">Show SQL — {source.kind} · {source.table ?? source.node_id}</div>
        {log.map((q, i) => (
          <div key={i} className={`mb-1 ${q.error ? 'text-red-400' : 'text-slate-300'}`}>
            <span className="text-accent">
              {q.error ? 'ERROR' : `${q.rows} rows${q.truncated ? ' (truncated)' : ''}`} · compile {q.compile_ms} ms · db {q.exec_ms} ms · round-trip {q.total_ms} ms
            </span>
            <div className="whitespace-pre-wrap break-all">{q.error ?? q.sql}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
