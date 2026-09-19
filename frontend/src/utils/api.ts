import type { Project, Connection, Variable, AgentProvider, RunRow } from '@/types'

const BASE = '/api'

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API ${res.status}: ${body}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  projects: {
    list:   ()           => req<Project[]>('/projects/'),
    get:    (id: string) => req<Project>(`/projects/${id}`),
    create: (name: string, description?: string) =>
      req<Project>('/projects/', { method: 'POST', body: JSON.stringify({ name, description }) }),
    save: (id: string, payload: object) =>
      req<Project>(`/projects/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
    delete: (id: string) => req<void>(`/projects/${id}`, { method: 'DELETE' }),
  },

  connections: {
    list:   () => req<Connection[]>('/connections/'),
    create: (data: object) =>
      req<Connection>('/connections/', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: string, data: object) =>
      req<Connection>(`/connections/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (id: string) => req<void>(`/connections/${id}`, { method: 'DELETE' }),
    test:   (id: string) =>
      req<{ ok: boolean; error?: string }>(`/connections/${id}/test`, { method: 'POST' }),
  },

  metadata: {
    listVars:  (scope = 'global') => req<Variable[]>(`/metadata/variables?scope=${scope}`),
    createVar: (data: object) =>
      req<Variable>('/metadata/variables', { method: 'POST', body: JSON.stringify(data) }),
    deleteVar: (id: string) => req<void>(`/metadata/variables/${id}`, { method: 'DELETE' }),
  },

  execute: {
    // Send the full live flow state so the backend always runs what's on screen,
    // not a potentially stale on-disk version.
    run: (project_id: string, flow_id: string, flow_state: object, start_from_node?: string, resume_from_node?: string) =>
      req<{ status: string }>('/execute/run', {
        method: 'POST',
        body: JSON.stringify({ project_id, flow_id, flow_state, start_from_node, resume_from_node }),
      }),
    flushPersist: (table_name: string, target = 'local') =>
      req<{ flushed: string }>('/execute/flush-persist', {
        method: 'POST',
        body: JSON.stringify({ table_name, target }),
      }),
    inspectFrame: (project_id: string, node_id: string, limit = 500) =>
      req<{ schema: object[]; rows: object[]; total: number }>(
        `/execute/frame/${project_id}/${node_id}?limit=${limit}`
      ),
    clearCache: (project_id: string, flow_id: string) =>
      req<void>(`/execute/clear-cache?project_id=${project_id}&flow_id=${flow_id}`, { method: 'POST' }),
  },

  runs: {
    list: (project_id?: string, limit = 50) =>
      req<RunRow[]>(`/runs/${project_id ? `?project_id=${project_id}&limit=${limit}` : `?limit=${limit}`}`),
  },

  capabilities: () => req<{
    engines: { name: string; label: string; description: string; tier: string;
               language: string; needs_target_connection: boolean; source: string;
               available: boolean; unavailable_reason?: string }[]
    plugins: { name: string; loaded: boolean; error?: string }[]
    features: Record<string, boolean>
  }>('/capabilities/'),

  buildFlow: (flow_state: object) =>
    req<{ nodes: { node_id: string; label: string; code: string }[]; errors: any[] }>(
      '/agent/build-flow', { method: 'POST', body: JSON.stringify({ flow_state }) }),

  customProcessors: {
    list: () => req<any[]>('/custom-processors/'),
    create: (data: object) =>
      req<any>('/custom-processors/', { method: 'POST', body: JSON.stringify(data) }),
    delete: (id: string) => req<void>(`/custom-processors/${id}`, { method: 'DELETE' }),
  },

  agent: {
    generate: (project_id: string, request: string, node_type: 'processor' | 'chart' | 'report', upstream_node_id?: string, engine: string = 'pandas') =>
      req<{ code: string | null; error: string | null; provider: string | null; had_context: boolean }>('/agent/generate', {
        method: 'POST',
        body: JSON.stringify({ project_id, request, node_type, upstream_node_id, engine }),
      }),
    listProviders: () =>
      req<AgentProvider[]>('/agent/providers'),
    createProvider: (data: object) =>
      req<AgentProvider>('/agent/providers', { method: 'POST', body: JSON.stringify(data) }),
    updateProvider: (id: string, data: object) =>
      req<AgentProvider>(`/agent/providers/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    activateProvider: (id: string) =>
      req<{ ok: boolean }>(`/agent/providers/${id}/activate`, { method: 'POST' }),
    testProvider: (id: string) =>
      req<{ ok: boolean; error?: string; sample?: string }>(`/agent/providers/${id}/test`, { method: 'POST' }),
    deleteProvider: (id: string) =>
      req<void>(`/agent/providers/${id}`, { method: 'DELETE' }),
  },
}
