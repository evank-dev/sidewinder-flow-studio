// ── Node data ─────────────────────────────────────────────────────────────────

export type RunMode = 'manual' | 'schedule'
export type StopMode = 'hard' | 'tap'
export type ChartType = 'plotly' | 'png' | 'echarts'

export interface TriggerData {
  label: string
  run_mode: RunMode
  cron: string
  timezone: string
}

export interface PersistConfig {
  enabled: boolean
  target: string        // 'local' or a connection name
  table_name: string
  last_persisted?: number
}

export interface ProcessorData {
  label: string
  code: string
  engine?: 'pandas' | 'duckdb' | 'polars' | 'sql' | 'ibis'   // execution engine, default pandas
  target_connection?: string   // sql/ibis pushdown target
  sql_read_dialect?: string    // dialect you write in (sql engine)
  persist?: PersistConfig
}

export interface ExploreData {
  label: string
  report_name: string
}

export interface ReportData {
  label: string
  report_name: string
  code: string
}

export interface StopData {
  label: string
  mode: StopMode
}

export interface TableOutData {
  label: string
}

export interface ChartOutData {
  label: string
  code: string
}

// ── Execution events (from WebSocket) ─────────────────────────────────────────

export interface WsNodeStart {
  type: 'node_start'
  node_id: string
  label: string
  ts: number
}

export interface WsNodeComplete {
  type: 'node_complete'
  node_id: string
  label: string
  rows_in: number
  rows_out: number
  duration_ms: number
}

export interface WsNodeError {
  type: 'node_error'
  node_id: string
  label: string
  detail: string
  duration_ms: number
}

export interface WsNodeStopped {
  type: 'node_stopped'
  node_id: string
  label: string
  rows: number
  duration_ms: number
  schema: ColumnSchema[]
  rows: Record<string, unknown>[]
  total: number
}

export interface WsFlowComplete {
  type: 'flow_complete'
  duration_ms: number
  stopped: boolean
}

export interface WsChartReady {
  type: 'chart_ready'
  node_id: string
  label: string
  chart_type: ChartType
  payload: string
  duration_ms: number
}

export interface WsTableReady {
  type: 'table_ready'
  node_id: string
  label: string
  schema: ColumnSchema[]
  rows: Record<string, unknown>[]
  total: number
  duration_ms: number
}

export type WsEvent =
  | WsNodeStart | WsNodeComplete | WsNodeError
  | WsNodeStopped | WsFlowComplete | WsChartReady | WsTableReady

// ── Node execution state (derived from events) ────────────────────────────────

export type NodeStatus = 'idle' | 'running' | 'ok' | 'error' | 'stopped' | 'blocked'

export interface NodeExecState {
  status: NodeStatus
  report_name?: string
  report_url?: string
  report_kind?: string
  rows_in?: number
  rows_out?: number
  duration_ms?: number
  detail?: string
  // For output nodes:
  chart_type?: ChartType
  chart_payload?: string
  table_schema?: ColumnSchema[]
  table_rows?: Record<string, unknown>[]
  table_total?: number
}

// ── Domain ────────────────────────────────────────────────────────────────────

export interface ColumnSchema {
  name: string
  dtype: string
}

export interface Connection {
  id: string
  name: string
  dialect: string
  host?: string
  port?: number
  database?: string
  username?: string
}

export interface Variable {
  id: string
  scope: string
  key: string
  value?: string
  description?: string
}

export interface AgentProvider {
  id: string
  name: string
  provider_type: 'anthropic' | 'ollama' | 'openai_compatible'
  model: string
  base_url?: string
  has_api_key: boolean
  is_active: boolean
}

export interface FlowMeta {
  id: string
  name: string
  active: boolean
  imports: string
  shared_functions?: string
  nodes: unknown[]
  edges: unknown[]
  next_run?: string
}

export interface Project {
  id: string
  name: string
  description?: string
  created_at?: string
  updated_at?: string
  flows: FlowMeta[]
}


export interface RunRow {
  id: string
  flow_id: string
  flow_name?: string
  trigger: 'manual' | 'schedule'
  status: 'running' | 'ok' | 'error' | 'stopped'
  attempt: number
  started_at?: string
  duration_ms?: number
  nodes_ok?: number
  nodes_error?: number
  error?: string
}
