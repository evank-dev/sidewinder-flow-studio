import { useState, useRef, useEffect } from 'react'
import { Play, Save, Plus, FolderOpen, ChevronDown, Square, RefreshCw } from 'lucide-react'
import { useStore } from '@/store'
import { AboutDialog } from './AboutDialog'

export function TopBar() {
  const {
    projects, activeProject, activeFlowId, running,
    loadProjects, openProject, closeProject, createProject,
    saveProject, runFlow, clearExecState,
    addFlow, deleteFlow, toggleFlowActive, setActiveFlow,
    renameFlow, activeFlow,
  } = useStore()

  const [showProjects, setShowProjects] = useState(false)
  const [showAbout, setShowAbout] = useState(false)
  const [newName, setNewName] = useState('')
  // Per-flow inline rename state: flowId → editing name
  const [editingFlowId, setEditingFlowId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const renameInputRef = useRef<HTMLInputElement>(null)

  const flow = activeFlow()

  const handleCreate = async () => {
    if (!newName.trim()) return
    await createProject(newName.trim())
    setNewName('')
    setShowProjects(false)
  }

  const handleOpen = async () => {
    await loadProjects()
    setShowProjects(true)
  }

  const startRename = (e: React.MouseEvent, flowId: string, currentName: string) => {
    e.stopPropagation()
    setEditingFlowId(flowId)
    setEditingName(currentName)
    setTimeout(() => renameInputRef.current?.select(), 50)
  }

  const commitRename = () => {
    if (editingFlowId && editingName.trim()) {
      renameFlow(editingFlowId, editingName.trim())
    }
    setEditingFlowId(null)
  }

  // Close project dropdown when clicking outside
  useEffect(() => {
    if (!showProjects) return
    const handler = (e: MouseEvent) => {
      if (!(e.target as Element).closest('.project-picker')) {
        setShowProjects(false)
      }
    }
    window.addEventListener('mousedown', handler)
    return () => window.removeEventListener('mousedown', handler)
  }, [showProjects])

  return (
    <header className="flex items-center gap-2 px-4 py-2 bg-surface border-b border-canvas-border z-20 shrink-0">
      {/* Brand — click for About */}
      <div
        className="flex items-center gap-2 mr-3 shrink-0 cursor-pointer group"
        onClick={() => setShowAbout(true)}
        title="About Sidewinder Flow Studio"
      >
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-accent to-blue-600 flex items-center justify-center group-hover:brightness-110 transition-all">
          <span className="text-canvas-bg text-xs font-bold">FS</span>
        </div>
        <span className="text-sm font-semibold text-slate-200 hidden sm:block group-hover:text-accent transition-colors">
          Sidewinder Flow Studio
        </span>
      </div>

      {showAbout && <AboutDialog onClose={() => setShowAbout(false)} />}

      {/* Project picker */}
      <div className="relative shrink-0 project-picker">
        <button
          className="btn-ghost border border-canvas-border gap-1.5 max-w-44"
          onClick={handleOpen}
        >
          <FolderOpen size={13} />
          <span className="truncate text-xs">{activeProject?.name ?? 'Open Project'}</span>
          <ChevronDown size={11} />
        </button>

        {showProjects && (
          <div className="absolute top-full left-0 mt-1 w-72 bg-surface-raised border border-canvas-border rounded-xl shadow-node z-50 overflow-hidden">
            <div className="p-2 border-b border-canvas-border">
              <div className="flex gap-1">
                <input
                  className="input flex-1 text-xs py-1"
                  placeholder="New project name…"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                  autoFocus
                />
                <button className="btn-pri px-2 py-1" onClick={handleCreate}>
                  <Plus size={12} />
                </button>
              </div>
            </div>
            <div className="max-h-56 overflow-y-auto">
              {projects.length === 0 ? (
                <div className="p-3 text-xs text-muted italic">No projects yet</div>
              ) : (
                projects.map((p) => (
                  <div
                    key={p.id}
                    className={`flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-surface-overlay text-sm
                      ${activeProject?.id === p.id ? 'text-accent' : 'text-slate-300'}`}
                    onClick={() => { openProject(p.id); setShowProjects(false) }}
                  >
                    <FolderOpen size={12} className="shrink-0" />
                    <span className="flex-1 truncate">{p.name}</span>
                    <span className="text-xs text-subtle">{p.updated_at?.slice(0, 10)}</span>
                  </div>
                ))
              )}
            </div>
            {activeProject && (
              <div className="border-t border-canvas-border p-2">
                <button
                  className="btn-ghost w-full text-xs text-muted justify-center"
                  onClick={() => { closeProject(); setShowProjects(false) }}
                >
                  Close project
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Flow tabs */}
      {activeProject && (
        <div className="flex items-center gap-1 flex-1 overflow-x-auto min-w-0">
          {activeProject.flows.map((f) => (
            <div
              key={f.id}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs cursor-pointer transition-colors shrink-0 group
                ${activeFlowId === f.id
                  ? 'border-accent/50 bg-accent/10 text-accent'
                  : 'border-canvas-border text-muted hover:text-slate-300'}`}
              onClick={() => setActiveFlow(f.id)}
            >
              {/* Active/inactive dot */}
              <div
                className={`w-1.5 h-1.5 rounded-full shrink-0 cursor-pointer
                  ${f.active ? 'bg-status-ok' : 'bg-subtle'}`}
                title={f.active ? 'Active — click to deactivate' : 'Inactive — click to activate'}
                onClick={(e) => { e.stopPropagation(); toggleFlowActive(f.id) }}
              />

              {/* Flow name — double-click to rename */}
              {editingFlowId === f.id ? (
                <input
                  ref={renameInputRef}
                  className="bg-transparent border-b border-accent outline-none text-xs w-24 text-accent"
                  value={editingName}
                  onChange={(e) => setEditingName(e.target.value)}
                  onBlur={commitRename}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename()
                    if (e.key === 'Escape') setEditingFlowId(null)
                    e.stopPropagation()
                  }}
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <span
                  className="max-w-24 truncate"
                  title="Double-click to rename"
                  onDoubleClick={(e) => startRename(e, f.id, f.name)}
                >
                  {f.name}
                </span>
              )}

              {f.next_run && (
                <span className="text-xs text-muted hidden lg:block">
                  ⏰ {f.next_run.slice(11, 16)}
                </span>
              )}

              {activeProject.flows.length > 1 && (
                <span
                  className="opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-red-400 ml-0.5 leading-none transition-opacity"
                  title="Delete flow"
                  onClick={(e) => { e.stopPropagation(); deleteFlow(f.id) }}
                >
                  ×
                </span>
              )}
            </div>
          ))}

          <button
            className="btn-ghost px-2 py-1 text-xs shrink-0"
            onClick={addFlow}
            title="Add new flow"
          >
            <Plus size={11} />
          </button>
        </div>
      )}

      {/* Right actions */}
      <div className="flex items-center gap-2 ml-auto shrink-0">
        {activeProject && (
          <>
            <button
              className="btn-ghost"
              onClick={saveProject}
              title="Save project (Ctrl+S)"
            >
              <Save size={14} />
            </button>

            {running ? (
              <button
                className="btn-danger flex items-center gap-1.5"
                onClick={clearExecState}
                title="Stop execution"
              >
                <Square size={12} fill="currentColor" /> Stop
              </button>
            ) : (
              <>
                <button
                  className="btn-ghost"
                  onClick={() => { clearExecState(); runFlow() }}
                  disabled={!activeFlowId}
                  title="Clear cache and re-run from start"
                >
                  <RefreshCw size={13} />
                </button>
                <button
                  className="btn-pri gap-1.5"
                  onClick={() => runFlow()}
                  disabled={!activeFlowId}
                >
                  <Play size={13} /> Run Flow
                </button>
              </>
            )}
          </>
        )}
      </div>
    </header>
  )
}
