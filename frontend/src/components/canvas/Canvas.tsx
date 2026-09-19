import { useCallback, useMemo, useEffect, useState, useRef } from 'react'
import ReactFlow, {
  Background, Controls, MiniMap, BackgroundVariant,
  addEdge, useNodesState, useEdgesState, useReactFlow, ReactFlowProvider,
  type Connection, type Node, type Edge, type NodeChange, type EdgeChange,
} from 'reactflow'
import 'reactflow/dist/style.css'

import { TriggerNode }   from '@/components/nodes/TriggerNode'
import { ProcessorNode } from '@/components/nodes/ProcessorNode'
import { StopNode, TableOutNode, ChartOutNode, ProfileNode } from '@/components/nodes/OutputNodes'
import { ExploreNode, ReportNode } from '@/components/nodes/ReportNodes'
import { AnnotationNode } from '@/components/nodes/AnnotationNode'
import { AiStartNode, AiStepNode, AiEndNode } from '@/components/nodes/AiNotes'
import { FlowEdge }      from './FlowEdge'
import { ContextMenu }   from './ContextMenu'
import { useStore, registerCanvasCallbacks, unregisterCanvasCallbacks } from '@/store'

const NODE_TYPES = {
  trigger:   TriggerNode,
  processor: ProcessorNode,
  stop:      StopNode,
  table_out: TableOutNode,
  chart_out: ChartOutNode,
  explore_out: ExploreNode,
  report_out: ReportNode,
  annotation: AnnotationNode,
  profile_out: ProfileNode,
  ai_start: AiStartNode,
  ai_step: AiStepNode,
  ai_end: AiEndNode,
}
const EDGE_TYPES = { default: FlowEdge }

const NODE_DEFAULTS: Record<string, object> = {
  trigger:   { label: 'Start', run_mode: 'manual', cron: '', timezone: 'UTC' },
  processor: { label: 'Processor', code: '' },
  stop:      { label: 'Stop', mode: 'hard' },
  table_out: { label: 'Table View' },
  chart_out: { label: 'Chart View', code: '' },
  explore_out: { label: 'Explore', report_name: '' },
  report_out:  { label: 'Report', report_name: '', code: '' },
  annotation: { text: 'Note', color: 'slate', fontSize: 14 },
  profile_out: { label: 'Profile', top_n: 5, hist_bins: 10 },
  ai_start: { label: 'Source', source_mode: 'sql' },
  ai_step:  { label: 'Transform', logic: '' },
  ai_end:   { label: 'Load', target_mode: 'db', write_mode: 'replace' },
}

interface CanvasInnerProps { flowId: string }

function CanvasInner({ flowId }: CanvasInnerProps) {
  const { activeProject, updateFlowCanvas, setSelectedNode } = useStore()
  const { screenToFlowPosition } = useReactFlow()

  const [contextMenu, setContextMenu] = useState<{
    nodeId: string; nodeType: string; x: number; y: number
  } | null>(null)

  const flow = activeProject?.flows.find((f) => f.id === flowId)
  const initialNodes = useMemo(() => (flow?.nodes ?? []) as Node[], [flowId])
  const initialEdges = useMemo(() => (flow?.edges ?? []) as Edge[], [flowId])

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  // Keep refs so the get callbacks always return the latest value
  const nodesRef = useRef(nodes)
  const edgesRef = useRef(edges)
  useEffect(() => { nodesRef.current = nodes }, [nodes])
  useEffect(() => { edgesRef.current = edges }, [edges])

  // Register all four canvas callbacks so the store can:
  //  - push node data changes (updateNodeData, toggleStopMode)
  //  - add/remove nodes (addNodeToCanvas, removeNodesFromCanvas, duplicateNode)
  //  - add/remove edges (addEdgesToCanvas)
  //  - read current state before running (runFlow syncs RF → store)
  useEffect(() => {
    registerCanvasCallbacks(
      setNodes,
      setEdges,
      () => nodesRef.current,
      () => edgesRef.current,
    )
    return () => unregisterCanvasCallbacks()
  }, [setNodes, setEdges])

  // Persist canvas on every RF change (move, delete, select, etc.)
  const handleNodesChange = useCallback((changes: NodeChange[]) => {
    onNodesChange(changes)
    setTimeout(() => {
      setNodes((current) => {
        updateFlowCanvas(flowId, current, edgesRef.current)
        return current
      })
    }, 0)
  }, [onNodesChange, flowId, updateFlowCanvas, setNodes])

  const handleEdgesChange = useCallback((changes: EdgeChange[]) => {
    onEdgesChange(changes)
    setTimeout(() => {
      setEdges((current) => {
        updateFlowCanvas(flowId, nodesRef.current, current)
        return current
      })
    }, 0)
  }, [onEdgesChange, flowId, updateFlowCanvas, setEdges])

  const onConnect = useCallback((c: Connection) => {
    setEdges((prev) => {
      const newEdges = addEdge({ ...c, type: 'default' }, prev)
      updateFlowCanvas(flowId, nodesRef.current, newEdges)
      return newEdges
    })
  }, [flowId, setEdges, updateFlowCanvas])

  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    const nodeType = event.dataTransfer.getData('application/fs-node-type')
    if (!nodeType) return
    const position = screenToFlowPosition({ x: event.clientX, y: event.clientY })
    const isAnnotation = nodeType === 'annotation'
    // If dragged from the Custom section, pre-fill code/engine/label
    let customData = {}
    const customRaw = event.dataTransfer.getData('application/fs-custom-processor')
    if (customRaw) {
      try { customData = JSON.parse(customRaw) } catch {}
    }
    const newNode: Node = {
      id: crypto.randomUUID(),
      type: nodeType,
      position,
      data: { ...(NODE_DEFAULTS[nodeType] ?? {}), ...customData },
      // Annotations render behind functional nodes and start with a usable size
      ...(isAnnotation
        ? { zIndex: -1, width: 220, height: 90, style: { width: 220, height: 90 } }
        : {}),
    }
    setNodes((prev) => {
      const newNodes = [...prev, newNode]
      updateFlowCanvas(flowId, newNodes, edgesRef.current)
      return newNodes
    })
  }, [flowId, setNodes, updateFlowCanvas, screenToFlowPosition])

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }, [])

  const onNodeContextMenu = useCallback((e: React.MouseEvent, node: Node) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenu({ nodeId: node.id, nodeType: node.type ?? 'processor', x: e.clientX, y: e.clientY })
  }, [])

  return (
    <>
      {contextMenu && (
        <ContextMenu
          nodeId={contextMenu.nodeId}
          nodeType={contextMenu.nodeType}
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
        />
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={onConnect}
        onPaneClick={() => { setSelectedNode(null); setContextMenu(null) }}
        onNodeClick={(_, n) => setSelectedNode(n.id)}
        onNodeContextMenu={onNodeContextMenu}
        onPaneContextMenu={(e) => e.preventDefault()}
        onDrop={onDrop}
        onDragOver={onDragOver}
        fitView
        deleteKeyCode="Delete"
        proOptions={{ hideAttribution: true }}
        className="bg-canvas-bg"
      >
        <Background variant={BackgroundVariant.Dots} gap={28} size={1} color="#1e2540" />
        <Controls className="!bg-surface !border-canvas-border" />
        <MiniMap
          nodeColor={(n) => ({
            trigger:   '#0ea5e9', processor: '#34d399',
            stop:      '#fb923c', table_out: '#818cf8', chart_out: '#e879f9',
            explore_out: '#2dd4bf', report_out: '#f472b6',
            annotation: '#475569', profile_out: '#22d3ee',
            ai_start: '#8b5cf6', ai_step: '#8b5cf6', ai_end: '#8b5cf6',
          }[n.type ?? ''] ?? '#2d3a52')}
          className="!bg-surface !border-canvas-border"
        />
      </ReactFlow>
    </>
  )
}

interface CanvasProps { flowId: string }
export function Canvas({ flowId }: CanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasInner flowId={flowId} />
    </ReactFlowProvider>
  )
}
