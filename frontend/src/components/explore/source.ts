// Explore source helpers — kept apart from ExploreView so importing them does
// not pull Graphic Walker into the main bundle.
import type { ExploreSource } from '@/types'

// Short stable hash so a SQL source has a compact key.
const hash = (t: string) => { let h = 0; for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) | 0; return (h >>> 0).toString(36) }

export const sourceKey = (s: ExploreSource) =>
  s.kind === 'frame' ? `frame:${s.project_id}:${s.node_id}`
    : s.kind === 'persist' ? `persist:${s.table}`
      : s.kind === 'table' ? `table:${s.connection}:${s.table}`
        : `sql:${s.connection}:${hash(s.sql)}`

export const isLive = (s: ExploreSource): s is Extract<ExploreSource, { connection: string }> =>
  s.kind === 'table' || s.kind === 'sql'

/** `#/explore?kind=…` ↔ source, so an Explore view can be bookmarked or linked to. */
export function sourceFromHash(hash: string): ExploreSource | null {
  if (!hash.startsWith('#/explore')) return null
  const q = Object.fromEntries(new URLSearchParams(hash.split('?')[1] ?? ''))
  if (q.kind === 'frame' && q.project_id && q.node_id) return { kind: 'frame', project_id: q.project_id, node_id: q.node_id }
  if (q.kind === 'persist' && q.table) return { kind: 'persist', table: q.table }
  if (q.kind === 'table' && q.connection && q.table) return { kind: 'table', connection: q.connection, table: q.table }
  if (q.kind === 'sql' && q.connection && q.sql) return { kind: 'sql', connection: q.connection, sql: q.sql }
  return null
}
