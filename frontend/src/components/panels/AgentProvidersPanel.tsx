/**
 * AgentProvidersPanel — manage AI providers for the code-generation agent.
 *
 * Mirrors the Connections panel: add/delete/test, with API keys stored
 * encrypted on the backend (never returned to the browser). One provider
 * is active at a time — that's the one the agent uses.
 */
import { useState, useEffect } from 'react'
import { Plus, Trash2, Check, X, TestTube2, Zap, Sparkles } from 'lucide-react'
import { api } from '@/utils/api'
import type { AgentProvider } from '@/types'

const PROVIDER_TYPES = [
  { value: 'anthropic',         label: 'Anthropic (Claude)',   needsKey: true,  needsUrl: false },
  { value: 'ollama',            label: 'Ollama (local)',       needsKey: false, needsUrl: true },
  { value: 'openai_compatible', label: 'OpenAI-compatible',    needsKey: true,  needsUrl: true },
] as const

const MODEL_HINTS: Record<string, string> = {
  anthropic: 'claude-sonnet-4-6',
  ollama: 'qwen2.5-coder:7b',
  openai_compatible: 'gpt-4o-mini',
}

const URL_HINTS: Record<string, string> = {
  anthropic: 'https://api.anthropic.com (optional)',
  ollama: 'http://localhost:11434',
  openai_compatible: 'https://your-endpoint/v1',
}

const emptyForm = { name: '', provider_type: 'ollama', model: '', base_url: '', api_key: '' }

export function AgentProvidersPanel() {
  const [providers, setProviders] = useState<AgentProvider[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState({ ...emptyForm })
  const [testRes, setTestRes] = useState<Record<string, { ok: boolean; msg?: string } | null>>({})
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try { setProviders(await api.agent.listProviders()) } catch { /* backend may not be updated */ }
  }
  useEffect(() => { load() }, [])

  const typeInfo = PROVIDER_TYPES.find((t) => t.value === form.provider_type)!

  const add = async () => {
    if (!form.name.trim() || !form.model.trim()) return
    setBusy(true)
    try {
      await api.agent.createProvider({
        name: form.name.trim(),
        provider_type: form.provider_type,
        model: form.model.trim(),
        base_url: form.base_url.trim() || null,
        api_key: form.api_key.trim() || null,
      })
      setForm({ ...emptyForm })
      setShowAdd(false)
      await load()
    } finally { setBusy(false) }
  }

  const test = async (id: string) => {
    setTestRes((r) => ({ ...r, [id]: null }))
    try {
      const res = await api.agent.testProvider(id)
      setTestRes((r) => ({ ...r, [id]: { ok: res.ok, msg: res.error } }))
    } catch (e: any) {
      setTestRes((r) => ({ ...r, [id]: { ok: false, msg: e.message } }))
    }
  }

  const activate = async (id: string) => { await api.agent.activateProvider(id); await load() }
  const remove   = async (id: string) => { await api.agent.deleteProvider(id); await load() }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        Configure AI providers for the code-generation agent. The <span className="text-accent">active</span> provider
        is used to generate processor and chart code. Keys are encrypted on the server.
      </p>

      {providers.map((p) => {
        const tr = testRes[p.id]
        return (
          <div
            key={p.id}
            className={`rounded-lg border p-3 space-y-1.5
              ${p.is_active ? 'border-accent/50 bg-accent/5' : 'border-canvas-border'}`}
          >
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-slate-200 flex-1 truncate">{p.name}</span>
              {p.is_active && (
                <span className="flex items-center gap-1 text-xs text-accent bg-accent/10 rounded px-1.5 py-0.5">
                  <Zap size={10} /> active
                </span>
              )}
              <button onClick={() => test(p.id)} className="btn-ghost p-1" title="Test connection">
                {tr === null
                  ? <div className="w-3 h-3 border border-accent border-t-transparent rounded-full animate-spin" />
                  : tr?.ok === true  ? <Check size={12} className="text-status-ok" />
                  : tr?.ok === false ? <X size={12} className="text-status-error" />
                  : <TestTube2 size={12} />}
              </button>
              <button onClick={() => remove(p.id)} className="btn-ghost p-1 text-red-400" title="Delete">
                <Trash2 size={12} />
              </button>
            </div>

            <div className="flex items-center gap-2 text-xs text-muted font-mono">
              <span className="bg-surface-overlay rounded px-1.5 py-0.5">
                {PROVIDER_TYPES.find((t) => t.value === p.provider_type)?.label ?? p.provider_type}
              </span>
              <span className="truncate">{p.model}</span>
            </div>

            {p.base_url && <div className="text-xs text-subtle font-mono truncate">{p.base_url}</div>}

            {tr?.ok === false && tr.msg && (
              <div className="text-xs text-red-300 bg-red-950/30 rounded p-1.5 break-words">{tr.msg}</div>
            )}

            {!p.is_active && (
              <button
                onClick={() => activate(p.id)}
                className="btn-ghost text-xs w-full justify-center border border-canvas-border mt-1"
              >
                <Zap size={11} /> Set active
              </button>
            )}
          </div>
        )
      })}

      {showAdd ? (
        <div className="rounded-lg border border-accent/30 p-3 space-y-2">
          <div>
            <label className="label">Name</label>
            <input className="input" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Local Qwen, Claude Premium" />
          </div>

          <div>
            <label className="label">Provider type</label>
            <select className="input" value={form.provider_type}
              onChange={(e) => setForm({ ...form, provider_type: e.target.value, model: '', base_url: '' })}>
              {PROVIDER_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>

          <div>
            <label className="label">Model</label>
            <input className="input font-mono" value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              placeholder={MODEL_HINTS[form.provider_type]} />
          </div>

          {typeInfo.needsUrl && (
            <div>
              <label className="label">Base URL</label>
              <input className="input font-mono" value={form.base_url}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                placeholder={URL_HINTS[form.provider_type]} />
            </div>
          )}

          {typeInfo.needsKey && (
            <div>
              <label className="label">API Key</label>
              <input type="password" className="input" value={form.api_key}
                onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                placeholder="sk-…" />
            </div>
          )}

          <div className="flex gap-2">
            <button className="btn-pri flex-1" onClick={add} disabled={busy}>
              {busy ? 'Adding…' : 'Add provider'}
            </button>
            <button className="btn-ghost" onClick={() => { setShowAdd(false); setForm({ ...emptyForm }) }}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          className="btn-ghost w-full justify-center border border-dashed border-canvas-border"
          onClick={() => setShowAdd(true)}
        >
          <Plus size={12} /> Add AI provider
        </button>
      )}

      {providers.length === 0 && !showAdd && (
        <div className="text-xs text-muted bg-canvas-bg rounded-lg border border-canvas-border p-3 flex gap-2">
          <Sparkles size={13} className="text-accent shrink-0 mt-0.5" />
          <span>
            No AI providers yet. Add a local Ollama model (no key, runs offline) or Anthropic Claude
            for the most capable option. Without a provider, the agent falls back to the
            <span className="font-mono"> ANTHROPIC_API_KEY</span> in your .env if set.
          </span>
        </div>
      )}
    </div>
  )
}
