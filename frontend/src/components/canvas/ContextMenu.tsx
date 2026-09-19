import { useEffect, useRef } from 'react'
import { Play, Copy, Trash2, Eye, OctagonX, Radio, Settings2, SplitSquareVertical, DatabaseZap, RotateCcw, Eraser } from 'lucide-react'
import { useStore } from '@/store'

interface ContextMenuProps {
  nodeId: string
  nodeType: string
  x: number
  y: number
  onClose: () => void
}

export function ContextMenu({ nodeId, nodeType, x, y, onClose }: ContextMenuProps) {
  const {
    activeProject, activeFlowId,
    setSelectedNode, setSidebarTab,
    runFlow, duplicateNode, execState,
    updateNodeData, removeNodesFromCanvas, addStopAfterNode, inspectNode,
  } = useStore()

  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent && e.key !== 'Escape') return
      if (e instanceof MouseEvent && menuRef.current?.contains(e.target as Node)) return
      onClose()
    }
    window.addEventListener('mousedown', handler)
    window.addEventListener('keydown', handler)
    return () => {
      window.removeEventListener('mousedown', handler)
      window.removeEventListener('keydown', handler)
    }
  }, [onClose])

  const menuStyle: React.CSSProperties = {
    position: 'fixed',
    top: Math.min(y, window.innerHeight - 280),
    left: Math.min(x, window.innerWidth - 220),
    zIndex: 9999,
  }

  const flow = activeProject?.flows.find((f) => f.id === activeFlowId)
  const state = execState[nodeId]
  const currentNode = (flow?.nodes as any[])?.find((n) => n.id === nodeId)
  const currentMode = currentNode?.data?.mode ?? 'hard'
  const persist = currentNode?.data?.persist as any

  // ── Actions ───────────────────────────────────────────────────────

  const openProps = () => { setSelectedNode(nodeId); setSidebarTab('properties'); onClose() }
  const viewOutput = () => { inspectNode(nodeId); onClose() }
  const runFromHere = () => { runFlow(nodeId); onClose() }

  const handleDuplicate = () => { duplicateNode(nodeId); onClose() }

  const handleDelete = () => {
    if (!activeFlowId) return
    removeNodesFromCanvas(activeFlowId, [nodeId])
    setSelectedNode(null)
    onClose()
  }

  const toggleStopMode = () => {
    if (!activeFlowId) return
    const newMode = currentMode === 'hard' ? 'tap' : 'hard'
    updateNodeData(activeFlowId, nodeId, { mode: newMode })
    onClose()
  }

  // Switch this hard stop to tap, then run just this branch from here.
  // Upstream frames are already cached, so only this branch re-executes.
  const releaseAndRun = () => {
    if (!activeFlowId) return
    updateNodeData(activeFlowId, nodeId, { mode: 'tap' })
    // Give the canvas/store a tick to sync the mode change before running
    setTimeout(() => runFlow(nodeId), 50)
    onClose()
  }

  const addStopAfter = (mode: 'hard' | 'tap') => {
    addStopAfterNode(nodeId, mode)
    onClose()
  }

  // ── Render ────────────────────────────────────────────────────────

  const Item = ({ icon, label, onClick, danger = false, dim = false }: {
    icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean; dim?: boolean
  }) => (
    <button
      className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm rounded-lg transition-colors text-left
        ${danger ? 'text-red-400 hover:bg-red-900/30'
          : dim  ? 'text-muted hover:bg-surface-overlay hover:text-slate-300'
                 : 'text-slate-200 hover:bg-surface-overlay'}`}
      onClick={onClick}
    >
      <span className="shrink-0 opacity-70">{icon}</span>
      {label}
    </button>
  )

  const Divider = () => <div className="my-1 border-t border-canvas-border" />

  return (
    <div
      ref={menuRef}
      style={menuStyle}
      className="w-52 bg-surface-raised border border-canvas-border rounded-xl shadow-node p-1.5 select-none"
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="px-3 py-1 text-xs text-muted uppercase tracking-wider font-medium border-b border-canvas-border mb-1">
        {nodeType.replace('_', ' ')}
      </div>

      <Item icon={<Settings2 size={13} />} label="Properties" onClick={openProps} />
      <Item icon={<Copy size={13} />}      label="Duplicate"   onClick={handleDuplicate} dim />

      {nodeType === 'processor' && (
        <>
          <Divider />
          <Item icon={<Play size={13} />}       label="Run from here"   onClick={runFromHere} />
          <Item
            icon={<DatabaseZap size={13} />}
            label={persist?.enabled ? 'Persist output: ON' : 'Persist output'}
            onClick={() => {
              if (!activeFlowId) return
              const next = persist?.enabled
                ? { ...persist, enabled: false }
                : { enabled: true, target: persist?.target ?? 'local', table_name: persist?.table_name ?? '' }
              updateNodeData(activeFlowId, nodeId, { persist: next })
              onClose()
            }}
            dim={!persist?.enabled}
          />
          {persist?.last_persisted && (
            <>
              <Item
                icon={<RotateCcw size={13} />}
                label="Resume from persisted"
                onClick={() => { runFlow(undefined, nodeId); onClose() }}
              />
              <Item
                icon={<Eraser size={13} />}
                label="Flush persisted data"
                onClick={async () => {
                  const { api } = await import('@/utils/api')
                  const tname = persist.table_name || (currentNode?.data?.label ?? '')
                  await api.execute.flushPersist(tname, persist.target ?? 'local')
                  if (activeFlowId) updateNodeData(activeFlowId, nodeId, {
                    persist: { ...persist, last_persisted: undefined },
                  })
                  onClose()
                }}
                dim
              />
            </>
          )}
          <Item icon={<OctagonX size={13} />}   label="Add Stop after"  onClick={() => addStopAfter('hard')} dim />
          <Item icon={<Radio size={13} />}      label="Add Tap after"   onClick={() => addStopAfter('tap')} dim />
        </>
      )}

      {nodeType === 'stop' && (
        <>
          <Divider />
          {(state?.table_rows || state?.status === 'stopped' || state?.status === 'ok') && (
            <Item icon={<Eye size={13} />} label="Inspect frame" onClick={viewOutput} />
          )}
          <Item
            icon={<SplitSquareVertical size={13} />}
            label={currentMode === 'hard' ? 'Switch to Tap (pass-through)' : 'Switch to Hard Stop'}
            onClick={toggleStopMode}
            dim
          />
          {currentMode === 'hard' ? (
            // In hard mode, the helpful action is: release this branch and run it
            <Item
              icon={<Play size={13} />}
              label="Release & run this branch"
              onClick={releaseAndRun}
            />
          ) : (
            // Already tap — just run downstream from here
            <Item
              icon={<Play size={13} />}
              label="Run from here"
              onClick={runFromHere}
            />
          )}
        </>
      )}

      {(nodeType === 'table_out' || nodeType === 'chart_out') && (
        <>
          <Divider />
          <Item icon={<Eye size={13} />} label="View output" onClick={viewOutput} />
        </>
      )}

      <Divider />
      <Item icon={<Trash2 size={13} />} label="Delete node" onClick={handleDelete} danger />
    </div>
  )
}
