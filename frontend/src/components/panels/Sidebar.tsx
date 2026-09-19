import { useRef, useCallback, useEffect } from 'react'
import { useStore } from '@/store'
import { TriggerPanel, ProcessorPanel, StopPanel, ChartOutPanel, TableOutPanel, ExplorePanel, ReportPanel } from './NodePanels'
import { AiStartPanel, AiStepPanel, AiEndPanel } from './AiNotePanels'
import { OutputPanel }  from './OutputPanel'
import { ImportsPanel } from './ImportsPanel'
import { MetadataPanel } from './MetadataPanel'
import { Settings2, FileCode2, BarChart3, Database, PanelRightClose, PanelRightOpen } from 'lucide-react'

type Tab = 'properties' | 'imports' | 'output' | 'metadata'

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: 'properties', label: 'Props',   icon: <Settings2 size={12} /> },
  { id: 'imports',    label: 'Imports', icon: <FileCode2 size={12} /> },
  { id: 'output',     label: 'Output',  icon: <BarChart3 size={12} /> },
  { id: 'metadata',   label: 'Meta',    icon: <Database size={12} /> },
]

function NodeProperties({ nodeId }: { nodeId: string }) {
  const { activeProject, activeFlowId } = useStore()
  const flow = activeProject?.flows.find((f) => f.id === activeFlowId)
  const node = (flow?.nodes as any[])?.find((n) => n.id === nodeId)
  if (!node) return <div className="p-4 text-xs text-muted italic">Node not found.</div>

  switch (node.type) {
    case 'trigger':   return <TriggerPanel   nodeId={nodeId} />
    case 'processor': return <ProcessorPanel nodeId={nodeId} />
    case 'stop':      return <StopPanel      nodeId={nodeId} />
    case 'chart_out': return <ChartOutPanel  nodeId={nodeId} />
    case 'table_out': return <TableOutPanel  nodeId={nodeId} />
    case 'explore_out': return <ExplorePanel nodeId={nodeId} />
    case 'report_out':  return <ReportPanel  nodeId={nodeId} />
    case 'ai_start': return <AiStartPanel nodeId={nodeId} />
    case 'ai_step':  return <AiStepPanel  nodeId={nodeId} />
    case 'ai_end':   return <AiEndPanel   nodeId={nodeId} />
    case 'profile_out': return (
      <div className="p-4 text-xs text-muted space-y-2">
        <p className="text-slate-300 font-medium">Profile</p>
        <p>Computes per-column stats on the incoming data: null counts, distinct
           counts, most common values, and min/max/mean/median/std with a mini
           histogram for numeric columns.</p>
        <p>Just connect it after any node and run — no configuration needed.
           Click the node to inspect the full profile table.</p>
      </div>
    )
    case 'annotation':  return (
      <div className="p-4 text-xs text-muted space-y-2">
        <p className="text-slate-300 font-medium">Annotation</p>
        <p>Double-click the note on the canvas to edit its text.</p>
        <p>When selected, drag the edges to resize, or click the colored dot (top-right) to cycle colors.</p>
        <p>Notes render behind your flow and never execute — they're just for documentation.</p>
      </div>
    )
    default: return <div className="p-4 text-xs text-muted">Unknown node type: {node.type}</div>
  }
}

export function Sidebar() {
  const {
    selectedNodeId, sidebarTab, setSidebarTab, running,
    sidebarVisible, setSidebarVisible,
    sidebarWidth, setSidebarWidth,
  } = useStore()

  const isDragging = useRef(false)
  const dragStartX = useRef(0)
  const dragStartW = useRef(0)
  const sidebarRef = useRef<HTMLDivElement>(null)

  // ── Resize drag logic ─────────────────────────────────────────────
  const onDragMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDragging.current = true
    dragStartX.current = e.clientX
    dragStartW.current = sidebarWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [sidebarWidth])

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return
      const delta = dragStartX.current - e.clientX
      const raw = dragStartW.current + delta
      // Snap to common widths when within 12px
      const snaps = [320, 380, 480, 600, 760]
      const snapped = snaps.find((s) => Math.abs(raw - s) < 12) ?? raw
      setSidebarWidth(snapped)
    }
    const onMouseUp = () => {
      if (!isDragging.current) return
      isDragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [setSidebarWidth])

  // ── Toggle button (always visible, even when sidebar is hidden) ───
  const ToggleButton = () => (
    <button
      onClick={() => setSidebarVisible(!sidebarVisible)}
      className="absolute left-0 top-1/2 -translate-x-full -translate-y-1/2 z-30
                 flex items-center justify-center w-5 h-12
                 bg-surface border border-canvas-border rounded-l-lg
                 text-muted hover:text-accent hover:bg-surface-raised
                 transition-colors cursor-pointer"
      title={sidebarVisible ? 'Hide sidebar' : 'Show sidebar'}
    >
      {sidebarVisible
        ? <PanelRightClose size={13} />
        : <PanelRightOpen  size={13} />
      }
    </button>
  )

  if (!sidebarVisible) {
    return (
      <div className="relative shrink-0 w-0">
        <ToggleButton />
      </div>
    )
  }

  return (
    <div
      ref={sidebarRef}
      className="relative flex flex-col bg-surface border-l border-canvas-border overflow-hidden shrink-0"
      style={{ width: sidebarWidth }}
    >
      {/* ── Drag handle — wider hit area, visible grip dots ─────── */}
      <div
        onMouseDown={onDragMouseDown}
        className="absolute left-0 top-0 bottom-0 w-3 z-20 cursor-col-resize group flex items-center justify-center"
        title="Drag to resize · Snaps to 320, 380, 480, 600, 760px"
      >
        {/* Thin line */}
        <div className="w-px h-full bg-canvas-border group-hover:bg-accent/50 transition-colors" />
        {/* Grip dots — visible on hover */}
        <div className="absolute top-1/2 -translate-y-1/2 flex flex-col gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {[0,1,2].map((i) => (
            <div key={i} className="w-1 h-1 rounded-full bg-accent/70" />
          ))}
        </div>
      </div>

      {/* ── Toggle button ──────────────────────────────────────── */}
      <ToggleButton />

      {/* ── Tab bar ────────────────────────────────────────────── */}
      <div className="flex border-b border-canvas-border shrink-0">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setSidebarTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-1 py-2.5 text-xs font-medium transition-colors
              ${sidebarTab === tab.id
                ? 'text-accent border-b-2 border-accent bg-accent/5'
                : 'text-muted hover:text-slate-300'}`}
          >
            {tab.icon}
            <span className={sidebarWidth < 340 ? 'hidden' : ''}>{tab.label}</span>
            {tab.id === 'output' && running && (
              <span className="w-1.5 h-1.5 rounded-full bg-status-running animate-pulse ml-0.5" />
            )}
          </button>
        ))}
      </div>

      {/* ── Panel content ──────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {sidebarTab === 'properties' ? (
          selectedNodeId ? (
            <NodeProperties nodeId={selectedNodeId} />
          ) : (
            <div className="p-4 text-xs text-muted italic">
              Click a node on the canvas to configure it.
            </div>
          )
        ) : sidebarTab === 'imports' ? (
          <ImportsPanel />
        ) : sidebarTab === 'output' ? (
          <OutputPanel />
        ) : (
          <MetadataPanel />
        )}
      </div>

      {/* ── Width indicator + snap buttons ─────────────────────── */}
      <div className="shrink-0 flex items-center gap-1 px-3 py-1 border-t border-canvas-border/50">
        <span className="text-xs text-subtle tabular-nums w-10">{sidebarWidth}px</span>
        {[320, 480, 600, 760].map((w) => (
          <button
            key={w}
            onClick={() => setSidebarWidth(w)}
            className={`text-xs px-1.5 py-0.5 rounded transition-colors
              ${Math.abs(sidebarWidth - w) < 10
                ? 'bg-accent/20 text-accent'
                : 'text-subtle hover:text-muted hover:bg-surface-overlay'}`}
            title={`Snap to ${w}px`}
          >
            {w}
          </button>
        ))}
      </div>
    </div>
  )
}
