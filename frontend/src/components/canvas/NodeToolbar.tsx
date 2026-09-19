import { Zap, Code2, OctagonX, Table2, BarChart3, Compass, LayoutDashboard, StickyNote, ScanSearch, Boxes, Trash2, Sparkles, DatabaseZap, Wand2, HardDriveDownload } from 'lucide-react'
import { useState, useEffect } from 'react'
import { useStore } from '@/store'
import { api } from '@/utils/api'

const NODES = [
  { type: 'trigger',   label: 'Trigger',    icon: <Zap size={13} />,       color: 'border-node-triggerBorder text-sky-300 bg-node-trigger' },
  { type: 'processor', label: 'Processor',  icon: <Code2 size={13} />,      color: 'border-node-processorBorder text-emerald-300 bg-node-processor' },
  { type: 'stop',      label: 'Stop / Tap', icon: <OctagonX size={13} />,   color: 'border-node-stopBorder text-orange-300 bg-node-stop' },
  { type: 'table_out', label: 'Table View', icon: <Table2 size={13} />,     color: 'border-node-tableOutBorder text-indigo-300 bg-node-tableOut' },
  { type: 'profile_out', label: 'Profile',   icon: <ScanSearch size={13} />,     color: 'border-cyan-500/50 text-cyan-300 bg-cyan-950/40' },
  { type: 'chart_out', label: 'Chart View', icon: <BarChart3 size={13} />,  color: 'border-node-chartOutBorder text-fuchsia-300 bg-node-chartOut' },
  { type: 'explore_out', label: 'Explore',  icon: <Compass size={13} />,        color: 'border-teal-500/50 text-teal-300 bg-teal-950/40' },
  { type: 'report_out',  label: 'Report',   icon: <LayoutDashboard size={13} />, color: 'border-pink-500/50 text-pink-300 bg-pink-950/40' },
  { type: 'annotation',  label: 'Note',     icon: <StickyNote size={13} />,      color: 'border-slate-500/50 text-slate-300 bg-slate-800/40' },
]

// Connectable AI notes — design a flow in plain language, then Build with AI
const AI_NOTES = [
  { type: 'ai_start', label: 'AI Start', icon: <DatabaseZap size={13} /> },
  { type: 'ai_step',  label: 'AI Step',  icon: <Wand2 size={13} /> },
  { type: 'ai_end',   label: 'AI End',   icon: <HardDriveDownload size={13} /> },
]

export function NodeToolbar() {
  const { activeProject, activeFlowId, applyBuiltFlow } = useStore()
  const flow = activeProject?.flows.find((f) => f.id === activeFlowId)
  const hasTrigger = (flow?.nodes as any[])?.some((n) => n.type === 'trigger')

  const [building, setBuilding] = useState(false)
  const [custom, setCustom] = useState<any[]>([])
  const loadCustom = async () => { try { setCustom(await api.customProcessors.list()) } catch {} }
  useEffect(() => {
    loadCustom()
    const h = () => loadCustom()
    window.addEventListener('sfs:custom-processors-changed', h)
    return () => window.removeEventListener('sfs:custom-processors-changed', h)
  }, [])

  const onDragStart = (e: React.DragEvent, type: string) => {
    e.dataTransfer.setData('application/fs-node-type', type)
    e.dataTransfer.effectAllowed = 'copy'
  }

  const onDragStartCustom = (e: React.DragEvent, cp: any) => {
    e.dataTransfer.setData('application/fs-node-type', 'processor')
    // Pre-fill payload the canvas will merge into the new node's data
    e.dataTransfer.setData('application/fs-custom-processor',
      JSON.stringify({ label: cp.name, code: cp.code, engine: cp.engine }))
    e.dataTransfer.effectAllowed = 'copy'
  }

  const hasAiNotes = (flow?.nodes as any[])?.some((n) => ['ai_start','ai_step','ai_end'].includes(n.type))

  const buildWithAI = async () => {
    if (!activeFlowId || !flow || building) return
    setBuilding(true)
    try {
      const res = await api.buildFlow(flow)
      if (res.nodes?.length) applyBuiltFlow(activeFlowId, res.nodes)
      if (res.errors?.length) {
        window.alert(`Built ${res.nodes.length} node(s); ${res.errors.length} failed:\n` +
          res.errors.map((e: any) => `• ${e.node_id}: ${e.error}`).join('\n'))
      } else if (!res.nodes?.length) {
        window.alert('No AI notes found to build.')
      }
    } catch (e: any) {
      window.alert('Build failed: ' + (e?.message ?? e))
    } finally {
      setBuilding(false)
    }
  }

  const deleteCustom = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    if (!window.confirm('Delete this custom processor?')) return
    await api.customProcessors.delete(id)
    loadCustom()
  }

  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-surface border-b border-canvas-border shrink-0 overflow-x-auto">
      <span className="text-xs text-muted uppercase tracking-wider mr-1 shrink-0">Add Node</span>
      {NODES.map((n) => {
        const isTriggerWarning = n.type === 'trigger' && hasTrigger
        return (
          <div
            key={n.type}
            draggable
            onDragStart={(e) => onDragStart(e, n.type)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium
                        cursor-grab active:cursor-grabbing transition-all select-none shrink-0
                        ${n.color}
                        ${isTriggerWarning ? 'opacity-50' : 'hover:brightness-125'}`}
            title={
              isTriggerWarning
                ? 'A trigger already exists in this flow'
                : `Drag onto canvas to add`
            }
          >
            {n.icon} {n.label}
            {isTriggerWarning && (
              <span className="text-xs opacity-70 ml-0.5">⚠</span>
            )}
          </div>
        )
      })}

      <div className="flex items-center gap-1 text-xs text-muted uppercase tracking-wider mx-1 shrink-0 border-l border-canvas-border pl-2">
        <Sparkles size={12} /> AI
      </div>
      {AI_NOTES.map((n) => (
        <div key={n.type} draggable onDragStart={(e) => onDragStart(e, n.type)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-dashed text-xs font-medium
                     cursor-grab active:cursor-grabbing select-none shrink-0
                     border-violet-500/60 text-violet-300 bg-violet-950/30 hover:brightness-125"
          title="Connectable AI note — describe intent, then Build with AI">
          {n.icon} {n.label}
        </div>
      ))}
      {hasAiNotes && (
        <button onClick={buildWithAI} disabled={building}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold shrink-0
                     bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-60 transition-colors">
          <Sparkles size={13} className={building ? 'animate-pulse' : ''} />
          {building ? 'Building…' : 'Build with AI'}
        </button>
      )}

      {custom.length > 0 && (
        <>
          <div className="flex items-center gap-1 text-xs text-muted uppercase tracking-wider mx-1 shrink-0 border-l border-canvas-border pl-2">
            <Boxes size={12} /> Custom
          </div>
          {custom.map((cp) => (
            <div
              key={cp.id}
              draggable
              onDragStart={(e) => onDragStartCustom(e, cp)}
              className="group flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium
                         cursor-grab active:cursor-grabbing transition-all select-none shrink-0
                         border-violet-500/50 text-violet-300 bg-violet-950/40 hover:brightness-125"
              title={cp.description || `Custom processor (${cp.engine}) — drag onto canvas`}
            >
              <Code2 size={13} /> {cp.name}
              <span className="text-[10px] opacity-60 font-mono">{cp.engine}</span>
              <button onClick={(e) => deleteCustom(e, cp.id)}
                className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-300 ml-0.5"
                title="Delete custom processor">
                <Trash2 size={10} />
              </button>
            </div>
          ))}
        </>
      )}

      <div className="ml-2 pl-2 border-l border-canvas-border text-xs text-muted shrink-0">
        Drag nodes onto canvas · Delete key removes selected
      </div>
    </div>
  )
}
