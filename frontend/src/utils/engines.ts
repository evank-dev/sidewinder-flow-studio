/**
 * The engine list from /api/capabilities, fetched once and shared by every
 * component that needs it (node cards, the processor panel).
 */
import { useEffect, useState } from 'react'
import { api } from './api'

export type EngineInfo = Awaited<ReturnType<typeof api.capabilities>>['engines'][number] & {
  params?: { key: string; label?: string; type?: string; default?: unknown; required?: boolean;
             options?: (string | { value: string; label?: string })[] }[]
  hint?: string
  has_to_code?: boolean
}

let cache: EngineInfo[] | null = null
let pending: Promise<EngineInfo[]> | null = null

export function loadEngines(): Promise<EngineInfo[]> {
  if (cache) return Promise.resolve(cache)
  pending ??= api.capabilities()
    .then((c) => (cache = (c?.engines ?? []) as EngineInfo[]))
    .catch(() => { pending = null; return [] })
  return pending
}

export function useEngines(): EngineInfo[] {
  const [engines, setEngines] = useState<EngineInfo[]>(cache ?? [])
  useEffect(() => {
    let live = true
    if (!cache) loadEngines().then((e) => { if (live) setEngines(e) })
    return () => { live = false }
  }, [])
  return engines
}

/** "Model: Exponential decay + offset · x column: t_s" — a form engine's settings at a glance. */
export function paramSummary(engine: EngineInfo | undefined, data: Record<string, any>): string {
  if (!engine?.params?.length) return ''
  const parts: string[] = []
  for (const p of engine.params) {
    let v = data[p.key]
    // Defaults only for required fields (e.g. the model), so optional
    // fields left untouched don't clutter the card
    if ((v === undefined || v === null || v === '') && p.required) v = p.default
    if (v === undefined || v === null || v === '' || p.type === 'boolean') continue
    if (p.type === 'select' && p.options) {
      const opt = p.options.find((o) => (typeof o === 'string' ? o : o.value) === v)
      if (opt && typeof opt !== 'string' && opt.label) v = opt.label
    }
    parts.push(`${p.label ?? p.key}: ${v}`)
  }
  return parts.join(' · ')
}
