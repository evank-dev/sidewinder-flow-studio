/**
 * Desktop edition, first run: where data lives (and the key to back up), and
 * a way in: a sample project, a curve-fitting example, or an empty project.
 * Closing it records that it was seen (/api/desktop/welcome-seen); About →
 * "Show the welcome screen again" brings it back.
 */
import { useEffect, useState } from 'react'
import { X, Table2, LineChart, FilePlus2 } from 'lucide-react'
import { api, type DesktopInfo } from '@/utils/api'
import { useStore } from '@/store'
import { DataLocations } from './DataLocations'

type Example = { name: string; description: string }

export function DesktopWelcome({ info, onClose }: { info: DesktopInfo; onClose: () => void }) {
  const { loadProjects, openProject, createProject } = useStore()
  const [examples, setExamples] = useState<Example[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.capabilities().then((c) => setExamples(c?.examples ?? [])).catch(() => {})
  }, [])

  const close = () => {
    api.desktop.welcomeSeen().catch(() => {})
    onClose()
  }
  const start = async (action: () => Promise<void>) => {
    if (busy) return
    setBusy(true)
    try { await action(); close() } finally { setBusy(false) }
  }
  const fromExample = (name: string) => start(async () => {
    const project = await api.projects.fromExample(name)
    await loadProjects()
    await openProject(project.id)
  })

  // The built-in CSV sample first, then one curve-fitting example if bundled
  const sample = examples.find((e) => e.name.startsWith('Sales pipeline'))
  const curvefit = examples.find((e) => e.name.startsWith('Curve fit'))

  const Choice = ({ icon, title, text, onClick }: { icon: React.ReactNode; title: string; text: string; onClick: () => void }) => (
    <button
      disabled={busy}
      onClick={onClick}
      className="text-left rounded-xl border border-canvas-border bg-surface p-3 hover:border-accent/60 hover:bg-surface-raised transition-colors disabled:opacity-50"
    >
      <div className="flex items-center gap-2 text-sm font-medium text-slate-200 mb-1">{icon}{title}</div>
      <div className="text-xs text-muted leading-relaxed">{text}</div>
    </button>
  )

  return (
    <div className="fixed inset-0 z-[9998] bg-black/60 flex items-center justify-center p-4">
      <div className="w-full max-w-2xl bg-surface-raised border border-canvas-border rounded-2xl shadow-node p-6 space-y-5">
        <div className="flex items-start gap-3">
          <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-accent to-blue-600 flex items-center justify-center shrink-0">
            <span className="text-canvas-bg text-sm font-bold">FS</span>
          </div>
          <div className="flex-1">
            <h2 className="text-base font-semibold text-slate-100">Welcome to Sidewinder Flow Studio</h2>
            <p className="text-sm text-muted mt-0.5">
              Build data pipelines as a canvas of steps: every node is Python or SQL, and you can see the data at each one.
            </p>
          </div>
          <button className="text-subtle hover:text-muted" title="Close" onClick={close}><X size={16} /></button>
        </div>

        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-wide text-subtle">Start with</div>
          <div className="grid grid-cols-3 gap-3">
            {sample && (
              <Choice icon={<Table2 size={14} className="text-accent" />} title="A sample pipeline"
                      text="Load a CSV, clean it, summarise it with SQL, chart it." onClick={() => fromExample(sample.name)} />
            )}
            {curvefit && (
              <Choice icon={<LineChart size={14} className="text-accent" />} title="Curve fitting"
                      text={curvefit.description} onClick={() => fromExample(curvefit.name)} />
            )}
            <Choice icon={<FilePlus2 size={14} className="text-accent" />} title="An empty project"
                    text="A canvas with a Start node. Add steps from the toolbar." onClick={() => start(() => createProject('My first project'))} />
          </div>
          <div className="text-xs text-subtle">More examples: Open Project → Start from an example.</div>
        </div>

        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-wide text-subtle">Your data stays on this computer</div>
          <DataLocations info={info} showLogs={false} />
          <div className="text-xs text-subtle">You can find this again in About (click the FS logo).</div>
        </div>
      </div>
    </div>
  )
}
