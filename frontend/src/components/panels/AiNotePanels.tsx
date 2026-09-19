/**
 * Panels for AI notes (ai_start / ai_step / ai_end) — the structured specs
 * that "Build with AI" compiles into processor code.
 */
import { useState, useEffect } from 'react'
import { useStore } from '@/store'

function useNodeData(nodeId: string): any {
  const { activeProject, activeFlowId } = useStore()
  const flow = activeProject?.flows.find((f) => f.id === activeFlowId)
  const node = (flow?.nodes as any[])?.find((n) => n.id === nodeId)
  return node?.data ?? {}
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
    </div>
  )
}

export function AiStartPanel({ nodeId }: { nodeId: string }) {
  const { activeFlowId, updateNodeData, connections } = useStore()
  const data = useNodeData(nodeId)
  const [f, setF] = useState<any>({})
  useEffect(() => { setF({
    label: data.label ?? 'Source', connection: data.connection ?? '',
    source_mode: data.source_mode ?? 'sql', sql: data.sql ?? '',
    table: data.table ?? '', columns: data.columns ?? '', filter: data.filter ?? '',
    group_by: data.group_by ?? '', file_path: data.file_path ?? '', file_pattern: data.file_pattern ?? '',
  }) }, [nodeId])

  const save = (patch: any = {}) => {
    const next = { ...f, ...patch }
    setF(next)
    if (activeFlowId) updateNodeData(activeFlowId, nodeId, next)
  }

  return (
    <div className="p-4 space-y-3">
      <h3 className="text-xs font-semibold text-violet-300 uppercase tracking-wider">✨ AI Start — Source Spec</h3>
      <p className="text-xs text-muted">Structured source so the AI knows your data exactly. Single table only — for joins/subqueries, provide the full SQL.</p>

      <Field label="Label"><input className="input" value={f.label ?? ''} onChange={(e) => save({ label: e.target.value })} /></Field>

      <Field label="Connection">
        <select className="input text-xs" value={f.connection ?? ''} onChange={(e) => save({ connection: e.target.value })}>
          <option value="">— pick a connection —</option>
          {connections.map((c: any) => <option key={c.id} value={c.name}>{c.name} ({c.dialect})</option>)}
        </select>
      </Field>

      <Field label="Source type">
        <div className="flex gap-1">
          {(['sql', 'table', 'file'] as const).map((m) => (
            <button key={m} onClick={() => save({ source_mode: m })}
              className={`flex-1 py-1.5 rounded border text-xs ${f.source_mode === m ? 'border-violet-400 bg-violet-500/15 text-violet-300' : 'border-canvas-border text-muted'}`}>
              {m === 'sql' ? 'Full SQL' : m === 'table' ? 'Single table' : 'File'}
            </button>
          ))}
        </div>
      </Field>

      {f.source_mode === 'sql' && (
        <Field label="SQL (used verbatim — required for joins/subqueries)">
          <textarea className="input font-mono text-xs min-h-[100px]" value={f.sql ?? ''} onChange={(e) => save({ sql: e.target.value })}
            placeholder="SELECT date, price, currency FROM blogs.forex WHERE date >= '2026-01-01'" />
        </Field>
      )}

      {f.source_mode === 'table' && (
        <>
          <Field label="Table (schema.table)"><input className="input font-mono text-xs" value={f.table ?? ''} onChange={(e) => save({ table: e.target.value })} placeholder="blogs.forex" /></Field>
          <Field label="Columns (comma-separated — pins the output schema)"><input className="input font-mono text-xs" value={f.columns ?? ''} onChange={(e) => save({ columns: e.target.value })} placeholder="date, price, currency" /></Field>
          <Field label="Filter (optional WHERE)"><input className="input font-mono text-xs" value={f.filter ?? ''} onChange={(e) => save({ filter: e.target.value })} placeholder="date >= '2026-01-01'" /></Field>
          <Field label="Group by (optional)"><input className="input font-mono text-xs" value={f.group_by ?? ''} onChange={(e) => save({ group_by: e.target.value })} placeholder="currency" /></Field>
        </>
      )}

      {f.source_mode === 'file' && (
        <>
          <Field label="File path (visible to the backend/container)"><input className="input font-mono text-xs" value={f.file_path ?? ''} onChange={(e) => save({ file_path: e.target.value })} placeholder="/data/imports/export_2026-07-01.csv" /></Field>
          <Field label="Pattern (optional, for many files)"><input className="input font-mono text-xs" value={f.file_pattern ?? ''} onChange={(e) => save({ file_pattern: e.target.value })} placeholder="export_*.csv" /></Field>
          <p className="text-xs text-muted">Messy files (multi-headers, junk rows)? Use a normal Processor to clean first, then start AI Steps after it.</p>
        </>
      )}
    </div>
  )
}

export function AiStepPanel({ nodeId }: { nodeId: string }) {
  const { activeFlowId, updateNodeData } = useStore()
  const data = useNodeData(nodeId)
  const [f, setF] = useState<any>({})
  useEffect(() => { setF({ label: data.label ?? 'Transform', logic: data.logic ?? '', output_columns: data.output_columns ?? '' }) }, [nodeId])
  const save = (patch: any = {}) => {
    const next = { ...f, ...patch }; setF(next)
    if (activeFlowId) updateNodeData(activeFlowId, nodeId, next)
  }
  return (
    <div className="p-4 space-y-3">
      <h3 className="text-xs font-semibold text-violet-300 uppercase tracking-wider">✨ AI Step — Transform</h3>
      <Field label="Label"><input className="input" value={f.label ?? ''} onChange={(e) => save({ label: e.target.value })} /></Field>
      <Field label="What should this step do?">
        <textarea className="input text-xs min-h-[110px]" value={f.logic ?? ''} onChange={(e) => save({ logic: e.target.value })}
          placeholder="e.g. aggregate to monthly average price per currency; month as YYYY-MM" />
      </Field>
      <Field label="Expected output columns (optional but improves the chain)">
        <input className="input font-mono text-xs" value={f.output_columns ?? ''} onChange={(e) => save({ output_columns: e.target.value })}
          placeholder="month, currency, avg_price" />
      </Field>
      <p className="text-xs text-muted">Naming the output columns pins the schema contract for the next node.</p>
    </div>
  )
}

export function AiEndPanel({ nodeId }: { nodeId: string }) {
  const { activeFlowId, updateNodeData, connections } = useStore()
  const data = useNodeData(nodeId)
  const [f, setF] = useState<any>({})
  useEffect(() => { setF({
    label: data.label ?? 'Load', connection: data.connection ?? '', target_mode: data.target_mode ?? 'db',
    table: data.table ?? '', write_mode: data.write_mode ?? 'replace',
    temp_table: data.temp_table ?? '', custom_sql: data.custom_sql ?? '', file_path: data.file_path ?? '',
  }) }, [nodeId])
  const save = (patch: any = {}) => {
    const next = { ...f, ...patch }; setF(next)
    if (activeFlowId) updateNodeData(activeFlowId, nodeId, next)
  }
  return (
    <div className="p-4 space-y-3">
      <h3 className="text-xs font-semibold text-violet-300 uppercase tracking-wider">✨ AI End — Load Spec</h3>

      <Field label="Label"><input className="input" value={f.label ?? ''} onChange={(e) => save({ label: e.target.value })} /></Field>

      <Field label="Target type">
        <div className="flex gap-1">
          {(['db', 'file'] as const).map((m) => (
            <button key={m} onClick={() => save({ target_mode: m })}
              className={`flex-1 py-1.5 rounded border text-xs ${f.target_mode === m ? 'border-violet-400 bg-violet-500/15 text-violet-300' : 'border-canvas-border text-muted'}`}>
              {m === 'db' ? 'Database' : 'File'}
            </button>
          ))}
        </div>
      </Field>

      {f.target_mode === 'db' && (
        <>
          <Field label="Connection">
            <select className="input text-xs" value={f.connection ?? ''} onChange={(e) => save({ connection: e.target.value })}>
              <option value="">— pick a connection —</option>
              {connections.map((c: any) => <option key={c.id} value={c.name}>{c.name} ({c.dialect})</option>)}
            </select>
          </Field>
          <Field label="Table"><input className="input font-mono text-xs" value={f.table ?? ''} onChange={(e) => save({ table: e.target.value })} placeholder="public.forex_monthly" /></Field>
          <Field label="Write mode">
            <div className="flex gap-1">
              {(['replace', 'append', 'custom'] as const).map((m) => (
                <button key={m} onClick={() => save({ write_mode: m })}
                  className={`flex-1 py-1.5 rounded border text-xs ${f.write_mode === m ? 'border-violet-400 bg-violet-500/15 text-violet-300' : 'border-canvas-border text-muted'}`}>
                  {m}
                </button>
              ))}
            </div>
          </Field>
          {f.write_mode === 'custom' && (
            <>
              <Field label="Temp table (df loads here first)">
                <input className="input font-mono text-xs" value={f.temp_table ?? ''} onChange={(e) => save({ temp_table: e.target.value })} placeholder="tmp_forex_load" />
              </Field>
              <Field label="Your upsert / merge SQL (runs after the temp load — used verbatim)">
                <textarea className="input font-mono text-xs min-h-[100px]" value={f.custom_sql ?? ''} onChange={(e) => save({ custom_sql: e.target.value })}
                  placeholder={"INSERT INTO forex_monthly SELECT * FROM tmp_forex_load\nON CONFLICT (month, currency) DO UPDATE SET avg_price = EXCLUDED.avg_price;"} />
              </Field>
            </>
          )}
        </>
      )}

      {f.target_mode === 'file' && (
        <Field label="Output file path (.csv / .xlsx / .parquet / .txt)">
          <input className="input font-mono text-xs" value={f.file_path ?? ''} onChange={(e) => save({ file_path: e.target.value })} placeholder="/data/outputs/forex_monthly.csv" />
        </Field>
      )}
    </div>
  )
}
