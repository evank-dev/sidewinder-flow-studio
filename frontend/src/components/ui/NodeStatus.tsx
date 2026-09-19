import { CheckCircle, XCircle, Loader2, OctagonX, Minus } from 'lucide-react'
import type { NodeStatus } from '@/types'

export function StatusIcon({ status }: { status: NodeStatus }) {
  switch (status) {
    case 'running': return <Loader2 size={12} className="text-status-running animate-spin" />
    case 'ok':      return <CheckCircle size={12} className="text-status-ok" />
    case 'error':   return <XCircle size={12} className="text-status-error" />
    case 'stopped': return <OctagonX size={12} className="text-status-stopped" />
    default:        return <Minus size={12} className="text-muted" />
  }
}

export function RowPill({ rows, color = 'text-accent' }: { rows: number; color?: string }) {
  return (
    <span className={`row-pill bg-surface-overlay ${color} tabular-nums`}>
      {rows.toLocaleString()} rows
    </span>
  )
}

export function DurationBadge({ ms }: { ms: number }) {
  return (
    <span className="text-xs text-muted font-mono tabular-nums">
      {ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`}
    </span>
  )
}
