// Explore source helpers — kept apart from ExploreView so importing them does
// not pull Graphic Walker into the main bundle.
import type { ExploreSource } from '@/types'

export const sourceKey = (s: ExploreSource) =>
  s.kind === 'frame' ? `frame:${s.project_id}:${s.node_id}` : `${s.kind}:${'connection' in s ? s.connection + ':' : ''}${s.table}`

/** `#/explore?kind=…` ↔ source, so an Explore view can be bookmarked or linked to. */
export function sourceFromHash(hash: string): ExploreSource | null {
  if (!hash.startsWith('#/explore')) return null
  const q = Object.fromEntries(new URLSearchParams(hash.split('?')[1] ?? ''))
  if (q.kind === 'frame' && q.project_id && q.node_id) return { kind: 'frame', project_id: q.project_id, node_id: q.node_id }
  if (q.kind === 'persist' && q.table) return { kind: 'persist', table: q.table }
  if (q.kind === 'table' && q.connection && q.table) return { kind: 'table', connection: q.connection, table: q.table }
  return null
}
