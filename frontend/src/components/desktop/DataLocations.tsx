/**
 * Desktop edition: where the user's data lives, with buttons to open the
 * folders and read the logs. Shown in the welcome screen and the About dialog.
 */
import { useEffect, useState } from 'react'
import { FolderOpen, KeyRound, ScrollText, X, RefreshCw } from 'lucide-react'
import { api, type DesktopInfo } from '@/utils/api'

function PathRow({ label, path, onOpen }: { label: string; path: string; onOpen?: () => void }) {
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 shrink-0 text-muted">{label}</div>
      <code className="flex-1 min-w-0 truncate font-mono text-[11px] text-slate-300 select-all" title={path}>{path}</code>
      {onOpen && (
        <button className="shrink-0 flex items-center gap-1 text-accent hover:underline" onClick={onOpen}>
          <FolderOpen size={12} /> Open
        </button>
      )}
    </div>
  )
}

export function LogViewer({ name, onClose }: { name: string; onClose: () => void }) {
  const [log, setLog] = useState<{ text: string; truncated: boolean } | null>(null)
  const [error, setError] = useState('')
  const load = () => api.desktop.log(name).then(setLog).catch((e) => setError(String(e?.message ?? e)))
  useEffect(() => { load() }, [name])

  return (
    <div className="fixed inset-0 z-[10000] bg-black/70 flex items-center justify-center p-6" onMouseDown={(e) => e.stopPropagation()}>
      <div className="w-full max-w-4xl h-[80vh] flex flex-col bg-surface-raised border border-canvas-border rounded-2xl shadow-node">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-canvas-border">
          <ScrollText size={14} className="text-accent" />
          <span className="text-sm font-medium text-slate-200">{name}</span>
          {log?.truncated && <span className="text-xs text-muted">(last 200 KB)</span>}
          <div className="flex-1" />
          <button className="text-subtle hover:text-muted" title="Reload" onClick={load}><RefreshCw size={14} /></button>
          <button className="text-subtle hover:text-muted" title="Close" onClick={onClose}><X size={16} /></button>
        </div>
        <pre className="flex-1 overflow-auto p-4 text-[11px] leading-relaxed font-mono text-slate-300 whitespace-pre-wrap">
          {error || (log ? log.text || '(empty)' : 'Loading…')}
        </pre>
      </div>
    </div>
  )
}

export function DataLocations({ info, showLogs = true }: { info: DesktopInfo; showLogs?: boolean }) {
  const [viewing, setViewing] = useState<string | null>(null)
  const open = (folder: 'data' | 'projects' | 'logs') => api.desktop.open(folder).catch(() => {})

  return (
    <div className="space-y-3 text-xs">
      <div className="space-y-1.5">
        <PathRow label="All data" path={info.data_dir} onOpen={() => open('data')} />
        <PathRow label="Projects" path={info.projects_dir} onOpen={() => open('projects')} />
      </div>

      <div className="flex gap-2 rounded-lg border border-amber-500/30 bg-amber-950/20 p-2.5 text-amber-200/90">
        <KeyRound size={14} className="shrink-0 mt-0.5 text-amber-400" />
        <div className="space-y-1 min-w-0">
          <div>
            <span className="font-medium">Back up <code className="font-mono">secret.key</code></span> with your
            projects. It encrypts the passwords of saved database connections; without it they can't be read
            and must be entered again.
          </div>
          <code className="block truncate font-mono text-[11px] text-amber-100/80 select-all" title={info.secret_key}>
            {info.secret_key}
          </code>
        </div>
      </div>

      {showLogs && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <div className="w-20 shrink-0 text-muted">Logs</div>
            <div className="flex-1 flex flex-wrap gap-x-3 gap-y-1">
              {info.logs.length === 0 && <span className="text-subtle">none yet</span>}
              {info.logs.map((l) => (
                <button key={l.name} className="font-mono text-[11px] text-accent hover:underline" onClick={() => setViewing(l.name)}>
                  {l.name}
                </button>
              ))}
            </div>
            <button className="shrink-0 flex items-center gap-1 text-accent hover:underline" onClick={() => open('logs')}>
              <FolderOpen size={12} /> Open
            </button>
          </div>
        </div>
      )}

      {viewing && <LogViewer name={viewing} onClose={() => setViewing(null)} />}
    </div>
  )
}
